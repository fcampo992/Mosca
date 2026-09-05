"""
Admin_Module — gestión de torneos, categorías y arqueros.

Expone funciones puras (sin estado) que operan sobre la conexión
singleton proporcionada por DB_Module (get_connection()).
"""

import re
import uuid

from archer.db import get_connection
from archer.modules.leaderboard import broadcast_update


# ---------------------------------------------------------------------------
# Torneos (Requerimientos 2.1, 2.2, 2.6, 2.7, 2.8, 2.9)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Transiciones de estado válidas: {estado_actual: conjunto de estados destino permitidos}
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"active"},
    "active": {"finished"},
    "finished": set(),
}


def create_tournament(name: str, date: str, rounds: int = 10, arrows_per_end: int = 5, rounds_count: int = 1) -> dict:
    """Crea un torneo con estado 'created' y un UUID v4 como identificador.

    - rounds       = tandas por ronda (ends_per_round), default 10
    - arrows_per_end = flechas por tanda, default 5
    - rounds_count   = cantidad de rondas del torneo, default 1
    """
    if not name or len(name) > 150:
        return {"error": "El nombre debe tener entre 1 y 150 caracteres.", "field": "name"}

    if not _DATE_RE.match(date):
        return {"error": "La fecha debe tener el formato YYYY-MM-DD.", "field": "date"}

    try:
        rounds_count = int(rounds_count)
    except (TypeError, ValueError):
        return {"error": "La cantidad de rondas debe estar entre 1 y 20.", "field": "rounds_count"}
    if not (1 <= rounds_count <= 20):
        return {"error": "La cantidad de rondas debe estar entre 1 y 20.", "field": "rounds_count"}

    try:
        rounds = int(rounds)
    except (TypeError, ValueError):
        return {"error": "Las tandas por ronda deben estar entre 1 y 20.", "field": "rounds"}
    if not (1 <= rounds <= 20):
        return {"error": "Las tandas por ronda deben estar entre 1 y 20.", "field": "rounds"}

    try:
        arrows_per_end = int(arrows_per_end)
    except (TypeError, ValueError):
        return {"error": "Las flechas por tanda deben estar entre 1 y 12.", "field": "arrows_per_end"}
    if not (1 <= arrows_per_end <= 12):
        return {"error": "Las flechas por tanda deben estar entre 1 y 12.", "field": "arrows_per_end"}

    conn = get_connection()
    tournament_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO tournaments (id, name, date, status, rounds, arrows_per_end, rounds_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tournament_id, name, date, "created", rounds, arrows_per_end, rounds_count),
    )
    try:
        conn.commit()
    except Exception:
        pass

    cursor = conn.execute(
        "SELECT id, name, date, status, rounds, arrows_per_end, rounds_count, created_at FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    row = cursor.fetchone()
    return dict(row)


def get_tournament(tournament_id: str) -> dict | None:
    """Retorna el dict de un torneo dado su id, o None si no existe (Req 2.6, 2.7)."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row)


def list_tournaments() -> list[dict]:
    """Retorna todos los torneos ordenados por created_at DESC (Req 2.9)."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, name, date, status, rounds, arrows_per_end, created_at FROM tournaments ORDER BY created_at DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def delete_tournament(tournament_id: str) -> dict:
    """Elimina un torneo en estado 'created' y sus categorías y registraciones asociadas.

    Validaciones (Req 2.8):
    - Torneo no encontrado → {'error': 'Torneo no encontrado.', 'status_code': 404}.
    - Torneo en estado distinto de 'created'
      → {'error': "Solo se pueden eliminar torneos en estado 'created'.", 'status_code': 409}.

    Eliminación en cascada manual: registrations → categories → tournaments.
    Retorna {} en caso de éxito.
    """
    conn = get_connection()

    cursor = conn.execute(
        "SELECT id, status FROM tournaments WHERE id = ?", (tournament_id,)
    )
    row = cursor.fetchone()
    if row is None:
        return {"error": "Torneo no encontrado.", "status_code": 404}

    if row["status"] != "created":
        return {
            "error": "Solo se pueden eliminar torneos en estado 'created'.",
            "status_code": 409,
        }

    conn.execute("DELETE FROM registrations WHERE tournament_id = ?", (tournament_id,))
    conn.execute("DELETE FROM categories WHERE tournament_id = ?", (tournament_id,))
    conn.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
    try:
        conn.commit()
    except Exception:
        pass

    return {}


def change_tournament_status(tournament_id: str, new_status: str) -> dict:
    """Cambia el estado de un torneo aplicando la máquina de estados (Req 2.6, 2.7, 2.8).

    Transiciones válidas: created→active, active→finished.
    Transiciones inválidas: finished→*, active→created.

    Retorna el dict del torneo actualizado en caso de éxito.
    """
    conn = get_connection()

    # Obtener el estado actual del torneo
    cursor = conn.execute(
        "SELECT id, name, date, status, created_at FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return {"error": "Torneo no encontrado"}

    current_status = row["status"]

    # Validar transición
    if new_status not in _VALID_TRANSITIONS.get(current_status, set()):
        return {
            "error": f"Transición de estado no permitida: {current_status} → {new_status}"
        }

    conn.execute(
        "UPDATE tournaments SET status = ? WHERE id = ?",
        (new_status, tournament_id),
    )
    try:
        conn.commit()
    except Exception:
        pass

    cursor = conn.execute(
        "SELECT id, name, date, status, created_at FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    return dict(cursor.fetchone())


# ---------------------------------------------------------------------------
# Categorías (Requerimientos 2.3, 2.4, 2.5)
# ---------------------------------------------------------------------------

def create_category(tournament_id: str, bow_type: str, distance: str, gender: str) -> dict:
    """Crea una categoría asociada a un torneo existente.

    Validaciones:
    - El torneo referenciado debe existir → error 'Torneo no encontrado'.
    - La combinación (tournament_id, bow_type, distance, gender) debe ser
      única → error 'La categoría ya existe para este torneo'.

    Retorna el dict de la categoría recién creada en caso de éxito.
    """
    conn = get_connection()

    # 1. Verificar existencia del torneo (Req 2.4)
    cursor = conn.execute(
        "SELECT id FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return {"error": "Torneo no encontrado"}

    # 2. Verificar unicidad de la combinación (Req 2.5)
    cursor = conn.execute(
        """
        SELECT id FROM categories
        WHERE tournament_id = ?
          AND bow_type      = ?
          AND distance      = ?
          AND gender        = ?
        """,
        (tournament_id, bow_type, distance, gender),
    )
    if cursor.fetchone() is not None:
        return {"error": "La categoría ya existe para este torneo"}

    # 3. Crear la categoría (Req 2.3)
    category_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO categories (id, tournament_id, bow_type, distance, gender)
        VALUES (?, ?, ?, ?, ?)
        """,
        (category_id, tournament_id, bow_type, distance, gender),
    )
    try:
        conn.commit()
    except Exception:
        pass  # libsql_experimental maneja commits de forma transparente

    return {
        "id": category_id,
        "tournament_id": tournament_id,
        "bow_type": bow_type,
        "distance": distance,
        "gender": gender,
    }


def list_categories(tournament_id: str) -> list[dict]:
    """Retorna todas las categorías asociadas al torneo indicado.

    Retorna una lista (posiblemente vacía) de dicts con los atributos
    de cada categoría.
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT id, tournament_id, bow_type, distance, gender
        FROM categories
        WHERE tournament_id = ?
        """,
        (tournament_id,),
    )
    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "tournament_id": row[1],
            "bow_type": row[2],
            "distance": row[3],
            "gender": row[4],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Arqueros e inscripciones (Requerimientos 3.x) — stubs para tareas futuras
# ---------------------------------------------------------------------------

_PIN_RE = re.compile(r"^\d{4}$")


def create_archer(name: str, pin: str) -> dict:
    """Crea un arquero con UUID v4, validando nombre y PIN.

    Validaciones (Req 3.1, 3.2, 3.3, 3.4):
    - name vacío o con más de 100 caracteres → error con field='name'.
    - pin no es exactamente 4 dígitos numéricos → error con field='pin'.
    - pin ya existe en la DB → error con field='pin'.

    Retorna el dict del arquero recién creado en caso de éxito.
    """
    # Validar nombre (Req 3.3)
    if not name or len(name) > 100:
        return {
            "error": "El nombre debe tener entre 1 y 100 caracteres.",
            "field": "name",
        }

    # Validar formato del PIN (Req 3.2)
    if not _PIN_RE.match(pin):
        return {
            "error": "El PIN debe tener exactamente 4 dígitos numéricos.",
            "field": "pin",
        }

    conn = get_connection()

    # Verificar unicidad del PIN (Req 3.4)
    cursor = conn.execute("SELECT id FROM archers WHERE pin = ?", (pin,))
    if cursor.fetchone() is not None:
        return {"error": "El PIN ya está en uso.", "field": "pin"}

    archer_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, pin, name),
    )
    try:
        conn.commit()
    except Exception:
        pass  # libsql_experimental gestiona commits de forma transparente

    cursor = conn.execute(
        "SELECT id, pin, name, created_at FROM archers WHERE id = ?",
        (archer_id,),
    )
    row = cursor.fetchone()
    return dict(row)


def list_archers() -> list[dict]:
    """Retorna todos los arqueros ordenados alfabéticamente por nombre ASC (Req 3.9)."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, pin, name, created_at FROM archers ORDER BY name ASC"
    )
    return [dict(row) for row in cursor.fetchall()]


def delete_archer(archer_id: str) -> dict:
    """Elimina un arquero si no tiene inscripciones en torneos activos o finalizados.

    Validaciones (Req 2.9):
    - Arquero no encontrado → {'error': 'Arquero no encontrado.', 'status_code': 404}.
    - Tiene inscripciones en torneos con status 'active' o 'finished'
      → {'error': '...', 'status_code': 409}.

    En caso de éxito elimina primero las inscripciones en torneos 'created' y
    luego el arquero; retorna {}.
    """
    conn = get_connection()

    # Verificar existencia del arquero
    cursor = conn.execute("SELECT id FROM archers WHERE id = ?", (archer_id,))
    if cursor.fetchone() is None:
        return {"error": "Arquero no encontrado.", "status_code": 404}

    # Verificar que no tiene participación en torneos activos o finalizados
    cursor = conn.execute(
        """SELECT r.id FROM registrations r
           JOIN tournaments t ON t.id = r.tournament_id
           WHERE r.archer_id = ? AND t.status IN ('active', 'finished')
           LIMIT 1""",
        (archer_id,),
    )
    if cursor.fetchone() is not None:
        return {
            "error": "No se puede eliminar: el arquero tiene participación en torneos activos o finalizados.",
            "status_code": 409,
        }

    # Eliminar inscripciones en torneos 'created' (cascada manual)
    conn.execute("DELETE FROM registrations WHERE archer_id = ?", (archer_id,))
    conn.execute("DELETE FROM archers WHERE id = ?", (archer_id,))
    try:
        conn.commit()
    except Exception:
        pass

    return {}


def list_enrolled_archers(tournament_id: str) -> list[dict]:
    """Retorna los arqueros inscritos en el torneo indicado (Req 2.7).

    Hace JOIN de registrations, archers y categories filtrando por tournament_id.
    Retorna lista de dicts con:
    - archer_id: UUID del arquero.
    - archer_name: nombre del arquero.
    - category: cadena legible "bow_type / distance / gender" (ej. "Recurvo / 70m / Masculino").

    Retorna lista vacía si no hay inscripciones.
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT
            a.id          AS archer_id,
            a.name        AS archer_name,
            c.bow_type,
            c.distance,
            c.gender
        FROM registrations r
        JOIN archers    a ON a.id = r.archer_id
        JOIN categories c ON c.id = r.category_id
        WHERE r.tournament_id = ?
        ORDER BY a.name ASC
        """,
        (tournament_id,),
    )
    rows = cursor.fetchall()
    return [
        {
            "archer_id": row["archer_id"],
            "archer_name": row["archer_name"],
            "category": f"{row['bow_type']} / {row['distance']} / {row['gender']}",
        }
        for row in rows
    ]


def enroll_archer(archer_id: str, tournament_id: str, category_id: str) -> dict:
    """Inscribe un arquero en una categoría de un torneo (Req 3.5, 3.6, 3.7, 3.8).

    Validaciones:
    - Torneo no encontrado → error.
    - Torneo en estado 'finished' → error (Req 3.6).
    - Arquero no encontrado → error.
    - category_id no pertenece al tournament_id → error (Req 3.7).
    - Inscripción duplicada → error (Req 3.8).

    Retorna el dict del registro recién creado en caso de éxito.
    """
    conn = get_connection()

    # Verificar existencia y estado del torneo
    cursor = conn.execute(
        "SELECT id, status FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    tournament_row = cursor.fetchone()
    if tournament_row is None:
        return {"error": "Torneo no encontrado."}
    if tournament_row["status"] == "finished":
        return {"error": "No se puede inscribir en un torneo finalizado."}

    # Verificar existencia del arquero
    cursor = conn.execute("SELECT id FROM archers WHERE id = ?", (archer_id,))
    if cursor.fetchone() is None:
        return {"error": "Arquero no encontrado."}

    # Verificar que la categoría pertenece al torneo (Req 3.7)
    cursor = conn.execute(
        "SELECT id FROM categories WHERE id = ? AND tournament_id = ?",
        (category_id, tournament_id),
    )
    if cursor.fetchone() is None:
        return {"error": "La categoría no corresponde al torneo."}

    # Verificar inscripción duplicada (Req 3.8)
    cursor = conn.execute(
        """
        SELECT id FROM registrations
        WHERE tournament_id = ? AND archer_id = ? AND category_id = ?
        """,
        (tournament_id, archer_id, category_id),
    )
    if cursor.fetchone() is not None:
        return {"error": "El arquero ya está registrado en esa categoría."}

    registration_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO registrations (id, tournament_id, archer_id, category_id)
        VALUES (?, ?, ?, ?)
        """,
        (registration_id, tournament_id, archer_id, category_id),
    )
    try:
        conn.commit()
    except Exception:
        pass

    return {
        "id": registration_id,
        "tournament_id": tournament_id,
        "archer_id": archer_id,
        "category_id": category_id,
    }


# ---------------------------------------------------------------------------
# Corrección de flechas por el administrador (Requerimientos 4.1, 4.2, 4.3, 4.4, 6.1, 6.2)
# ---------------------------------------------------------------------------

ARROW_POINTS: dict[str, int] = {
    "X": 10, "10": 10, "9": 9, "8": 8, "7": 7,
    "6": 6, "5": 5, "4": 4, "3": 3, "2": 2, "1": 1, "M": 0,
}

_VALID_ARROW_VALS: set[str] = set(ARROW_POINTS.keys())


def correct_arrow_admin(score_id: str, arrow_val: str) -> dict:
    """Corrige el valor de una flecha por su score_id (solo administrador).

    El administrador puede corregir cualquier flecha independientemente de la
    ronda o tanda a la que pertenezca (Req 4.1).

    Validaciones:
    - arrow_val no pertenece al conjunto válido → {"error": "...", "field": "arrow_val"} (Req 4.3).
    - score_id no existe en la tabla scores → {"error": "...", "status_code": 404} (Req 4.2).

    En caso de éxito:
    - Ejecuta UPDATE scores SET arrow_val=?, points=? WHERE id=?.
    - Llama a broadcast_update(tournament_id) del score actualizado (Req 4.4).
    - Retorna dict con todos los campos del score actualizado.
    """
    # Req 4.3 — Validar arrow_val
    if arrow_val not in _VALID_ARROW_VALS:
        return {
            "error": (
                "Valor de flecha inválido. Los valores válidos son: "
                "X, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, M."
            ),
            "field": "arrow_val",
        }

    conn = get_connection()

    # Req 4.2 — Buscar el score por score_id
    cursor = conn.execute(
        "SELECT id, tournament_id, archer_id, round_number, end_number, arrow_val, points "
        "FROM scores WHERE id = ?",
        (score_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return {"error": "Puntuación no encontrada.", "status_code": 404}

    tournament_id = row["tournament_id"]
    points = ARROW_POINTS[arrow_val]

    # Req 4.1, 6.1 — Actualizar arrow_val y points
    conn.execute(
        "UPDATE scores SET arrow_val = ?, points = ? WHERE id = ?",
        (arrow_val, points, score_id),
    )
    try:
        conn.commit()
    except Exception:
        pass  # libsql_experimental gestiona commits de forma transparente

    # Req 4.4 — Disparar actualización del leaderboard
    broadcast_update(tournament_id)

    # Retornar el score actualizado
    cursor = conn.execute(
        "SELECT id, tournament_id, archer_id, round_number, end_number, arrow_val, points "
        "FROM scores WHERE id = ?",
        (score_id,),
    )
    updated = cursor.fetchone()
    return dict(updated)


def update_archer(archer_id: str, name: str, pin: str) -> dict:
    """Actualiza nombre y/o PIN de un arquero existente.

    Validaciones:
    - name vacío o con más de 100 caracteres → error con field='name'.
    - pin no es exactamente 4 dígitos numéricos → error con field='pin'.
    - pin ya en uso por otro arquero → error con field='pin'.
    - archer no encontrado → error con status_code=404.

    Retorna dict del arquero actualizado o dict con 'error'.
    """
    name = (name or "").strip()
    pin  = (pin  or "").strip()

    if not name or len(name) > 100:
        return {"error": "El nombre debe tener entre 1 y 100 caracteres.", "field": "name"}

    if not _PIN_RE.match(pin):
        return {"error": "El PIN debe tener exactamente 4 dígitos numéricos.", "field": "pin"}

    conn = get_connection()

    row = conn.execute("SELECT id FROM archers WHERE id = ?", (archer_id,)).fetchone()
    if row is None:
        return {"error": "Arquero no encontrado.", "status_code": 404}

    # Verificar PIN único entre otros arqueros
    existing = conn.execute(
        "SELECT id FROM archers WHERE pin = ? AND id != ?", (pin, archer_id)
    ).fetchone()
    if existing is not None:
        return {"error": "El PIN ya está en uso por otro arquero.", "field": "pin"}

    conn.execute(
        "UPDATE archers SET name = ?, pin = ? WHERE id = ?",
        (name, pin, archer_id),
    )
    try:
        conn.commit()
    except Exception:
        pass

    row = conn.execute(
        "SELECT id, pin, name, created_at FROM archers WHERE id = ?", (archer_id,)
    ).fetchone()
    return dict(row)
