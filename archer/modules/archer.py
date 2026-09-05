"""
Archer_Module — autenticación por PIN y manejo de sesiones.

Expone:
  - authenticate_pin(pin)           Valida formato, aplica lockout en memoria, consulta DB.
  - get_active_tournament(archer_id) Retorna torneo activo en el que el arquero está inscrito.
  - is_session_valid(last_active)    Verifica que la sesión no haya expirado (≤ 30 min).
  - reset_lockout()                  Limpia el estado de lockout en memoria (solo para tests).
  - save_arrow(...)                  Persiste una flecha en la tabla scores.
  - correct_arrow_archer(...)        Corrige una flecha de la tanda activa del arquero.
  - get_end_summary(...)             Retorna resumen de una tanda (flechas + subtotal).
  - get_accumulated_points(...)      Retorna la suma total de puntos del arquero en el torneo.
  - get_end_arrow_count(...)         Retorna el número de flechas registradas en la tanda actual.

Requerimientos cubiertos: 2.4, 3.1, 3.2, 3.3, 3.4, 3.6, 4.1–4.7, 6.1, 6.2
"""

import re
import time
from datetime import datetime, timezone

from archer.db import get_connection

# ---------------------------------------------------------------------------
# Estado de bloqueo en memoria (Req 4.7)
# {pin: (attempt_count, block_until_timestamp)}
# ---------------------------------------------------------------------------
_lockout: dict[str, tuple[int, float]] = {}
_MAX_ATTEMPTS = 5
_BLOCK_SECONDS = 300  # 5 minutos

_PIN_RE = re.compile(r"^\d{4}$")

# ---------------------------------------------------------------------------
# Constantes de progresión de tanda (Req 2.1)
# ---------------------------------------------------------------------------
ARROWS_PER_END = 6   # Flechas por tanda (estándar FITA/World Archery)
ENDS_PER_ROUND = 10  # Tandas por ronda


def reset_lockout() -> None:
    """Limpia el estado de bloqueo en memoria.

    Función de ayuda para teardown de tests — no debe usarse en producción.
    """
    _lockout.clear()


# ---------------------------------------------------------------------------
# Autenticación (Req 4.1, 4.2, 4.6, 4.7)
# ---------------------------------------------------------------------------

def authenticate_pin(pin: str) -> dict:
    """Autentica a un arquero por su PIN de 4 dígitos numéricos.

    Flujo:
    1. Valida el formato del PIN (regex ^[0-9]{4}$) SIN consultar la DB.
       Si inválido → retorna error con field='pin'.
    2. Verifica si el PIN está bloqueado por exceso de intentos fallidos.
       Si bloqueado → retorna error con tiempo restante.
    3. Consulta la DB en busca del arquero con ese PIN.
       Si no existe → incrementa intentos; si llega a _MAX_ATTEMPTS bloquea 5 min.
    4. Si existe → resetea el contador de intentos y retorna datos del arquero.

    Returns:
        dict con 'archer_id', 'name', 'pin' en caso de éxito.
        dict con 'error' (y opcionalmente 'blocked': True) en caso de fallo.
    """
    # Paso 1: validar formato sin tocar la DB (Req 4.6)
    if not _PIN_RE.match(pin):
        return {
            "error": "El PIN debe tener exactamente 4 dígitos numéricos.",
            "field": "pin",
        }

    # Paso 2: verificar bloqueo (Req 4.7)
    attempt_count, block_until = _lockout.get(pin, (0, 0.0))
    if block_until > time.time():
        minutes_remaining = max(1, int((block_until - time.time()) / 60) + 1)
        return {
            "error": f"Demasiados intentos. Espere {minutes_remaining} minutos.",
            "blocked": True,
        }

    # Paso 3: consultar la DB
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, name, pin FROM archers WHERE pin = ?",
        (pin,),
    )
    row = cursor.fetchone()

    if row is None:
        # PIN no encontrado — incrementar contador (Req 4.2, 4.7)
        attempt_count += 1
        if attempt_count >= _MAX_ATTEMPTS:
            _lockout[pin] = (attempt_count, time.time() + _BLOCK_SECONDS)
        else:
            _lockout[pin] = (attempt_count, 0.0)
        return {"error": "PIN incorrecto."}

    # Paso 4: autenticación exitosa — resetear contador (Req 4.1)
    _lockout[pin] = (0, 0.0)
    return {
        "archer_id": row["id"],
        "name": row["name"],
        "pin": row["pin"],
    }


# ---------------------------------------------------------------------------
# Torneo activo (Req 4.3)
# ---------------------------------------------------------------------------

def get_active_tournament(archer_id: str) -> dict | None:
    """Retorna el torneo activo en el que el arquero está inscrito, o None.

    Realiza un JOIN entre registrations y tournaments filtrando por
    archer_id y status = 'active'.
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT t.id, t.name, t.date, t.status, t.created_at,
               t.rounds, t.arrows_per_end,
               COALESCE(t.rounds_count, 1) AS rounds_count
        FROM registrations r
        JOIN tournaments t ON t.id = r.tournament_id
        WHERE r.archer_id = ?
          AND t.status = 'active'
        LIMIT 1
        """,
        (archer_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Validación de sesión (Req 4.4)
# ---------------------------------------------------------------------------

def is_session_valid(last_active: str) -> bool:
    """Verifica si la sesión sigue activa basándose en el timestamp ISO last_active.

    La sesión es válida mientras (now - last_active) ≤ 30 minutos.

    Args:
        last_active: Cadena ISO 8601 producida por datetime.now().isoformat()
                     (tiempo local naive), por ejemplo '2024-09-20T14:30:00'.

    Returns:
        True si la sesión es válida (≤ 30 min), False si expiró.
    """
    try:
        last_dt = datetime.fromisoformat(last_active)
    except (ValueError, TypeError):
        return False

    # Normalizar: si last_active trae tzinfo lo eliminamos para comparar
    # ambos timestamps como naive en la misma zona horaria local.
    if last_dt.tzinfo is not None:
        last_dt = last_dt.replace(tzinfo=None)

    # Usar datetime.now() (tiempo local naive) para ser consistente con cómo
    # se almacena last_active en la sesión (datetime.now().isoformat()).
    now = datetime.now()
    delta_seconds = (now - last_dt).total_seconds()
    return delta_seconds <= 1800  # 30 minutos = 1800 segundos


# ---------------------------------------------------------------------------
# Mapeo de valores de flecha a puntos (Req 5.2)
# ---------------------------------------------------------------------------

ARROW_POINTS = {
    "X": 10, "10": 10,
    "9": 9, "8": 8, "7": 7, "6": 6,
    "5": 5, "4": 4, "3": 3, "2": 2, "1": 1,
    "M": 0,
}


# ---------------------------------------------------------------------------
# Carga de puntuaciones (Req 5.2, 5.3, 5.4, 5.5, 5.6, 5.7)
# ---------------------------------------------------------------------------

def save_arrow(
    archer_id: str,
    tournament_id: str,
    round_number: int,
    end_number: int,
    arrow_val: str,
) -> dict:
    """Persiste una flecha en la tabla scores.

    Validaciones previas:
    1. arrow_val debe estar en ARROW_POINTS.
    2. El torneo debe existir y tener status == 'active'.

    Returns:
        dict con los datos de la flecha persistida, o dict con 'error'.
    """
    # Paso 1: validar valor de flecha
    if arrow_val not in ARROW_POINTS:
        return {"error": "Valor de flecha inválido.", "field": "arrow_val"}

    # Paso 2: verificar que el torneo existe y está activo
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, status FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    tournament = cursor.fetchone()

    if tournament is None or tournament["status"] != "active":
        return {"error": "El torneo no está activo."}

    # Paso 3: mapear arrow_val a points y persistir
    import uuid as _uuid
    points = ARROW_POINTS[arrow_val]
    score_id = str(_uuid.uuid4())

    conn.execute(
        """
        INSERT INTO scores (id, tournament_id, archer_id, round_number, end_number, arrow_val, points)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (score_id, tournament_id, archer_id, round_number, end_number, arrow_val, points),
    )
    conn.commit()

    result = {
        "id": score_id,
        "tournament_id": tournament_id,
        "archer_id": archer_id,
        "round_number": round_number,
        "end_number": end_number,
        "arrow_val": arrow_val,
        "points": points,
    }

    # Paso 4: notificar al leaderboard (import lazy para evitar circular import)
    try:
        from archer.modules.leaderboard import broadcast_update  # type: ignore
        broadcast_update(tournament_id)
    except ImportError:
        pass

    return result


def get_end_summary(
    archer_id: str,
    tournament_id: str,
    round_number: int,
    end_number: int,
) -> dict:
    """Retorna el resumen de una tanda: lista de flechas y subtotal.

    Returns:
        dict con 'arrows' (lista de {id, arrow_val, points}) y 'subtotal' (int).
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT id, arrow_val, points
        FROM scores
        WHERE archer_id = ?
          AND tournament_id = ?
          AND round_number = ?
          AND end_number = ?
        ORDER BY created_at ASC
        """,
        (archer_id, tournament_id, round_number, end_number),
    )
    rows = cursor.fetchall()
    arrows = [{"id": row["id"], "arrow_val": row["arrow_val"], "points": row["points"]} for row in rows]
    subtotal = sum(a["points"] for a in arrows)
    return {"arrows": arrows, "subtotal": subtotal}


def get_accumulated_points(archer_id: str, tournament_id: str) -> int:
    """Retorna la suma total de puntos del arquero en el torneo.

    Returns:
        int — suma de points; 0 si no hay flechas registradas.
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT SUM(points) AS total
        FROM scores
        WHERE archer_id = ?
          AND tournament_id = ?
        """,
        (archer_id, tournament_id),
    )
    row = cursor.fetchone()
    if row is None or row["total"] is None:
        return 0
    return int(row["total"])


def correct_arrow_archer(
    score_id: str,
    arrow_val: str,
    archer_id: str,
    tournament_id: str,
    current_round: int,
    current_end: int,
) -> dict:
    """Corrige el valor de una flecha en la tanda activa del arquero.

    Reglas de negocio (Req 3.1–3.4, 3.6, 6.1, 6.2):
    1. Valida arrow_val contra los 12 valores canónicos.
    2. Verifica que el score existe y pertenece al archer_id/tournament_id.
    3. Verifica que el score pertenece a la tanda activa
       (round_number == current_round AND end_number == current_end).
       Si pertenece a ronda confirmada → error 403.
    4. Ejecuta UPDATE scores y llama a broadcast_update().

    Returns:
        dict con campos del score actualizado, o dict con 'error'.
    """
    # Paso 1: validar arrow_val (Req 3.3)
    if arrow_val not in ARROW_POINTS:
        return {"error": "Valor de flecha inválido.", "field": "arrow_val"}

    # Paso 2: buscar score y verificar propiedad (Req 3.4)
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT id, tournament_id, archer_id, round_number, end_number, arrow_val, points
        FROM scores
        WHERE id = ?
        """,
        (score_id,),
    )
    score = cursor.fetchone()

    if score is None or score["archer_id"] != archer_id or score["tournament_id"] != tournament_id:
        return {"error": "No tienes permiso para corregir esta flecha.", "status_code": 403}

    # Paso 3: verificar que pertenece a la tanda activa (Req 3.1, 3.2)
    score_round = score["round_number"]
    score_end = score["end_number"]

    is_active_end = (score_round == current_round and score_end == current_end)
    is_confirmed = (
        score_round < current_round
        or (score_round == current_round and score_end < current_end)
    )

    if is_confirmed:
        return {
            "error": "Solo un administrador puede corregir rondas confirmadas.",
            "status_code": 403,
        }

    if not is_active_end:
        # Caso de flecha en ronda/tanda futura — también es inaccesible para el arquero
        return {
            "error": "Solo puedes corregir flechas de la tanda activa.",
            "status_code": 403,
        }

    # Paso 4: aplicar la corrección (Req 6.1)
    points = ARROW_POINTS[arrow_val]
    conn.execute(
        "UPDATE scores SET arrow_val = ?, points = ? WHERE id = ?",
        (arrow_val, points, score_id),
    )
    conn.commit()

    result = {
        "id": score_id,
        "tournament_id": tournament_id,
        "archer_id": archer_id,
        "round_number": score_round,
        "end_number": score_end,
        "arrow_val": arrow_val,
        "points": points,
    }

    # Paso 5: notificar al leaderboard (Req 3.6)
    try:
        from archer.modules.leaderboard import broadcast_update  # type: ignore
        broadcast_update(tournament_id)
    except ImportError:
        pass

    return result


def get_end_arrow_count(
    archer_id: str,
    tournament_id: str,
    round_number: int,
    end_number: int,
) -> int:
    """Retorna el número de flechas registradas en la tanda actual.

    Args:
        archer_id:     UUID del arquero.
        tournament_id: UUID del torneo.
        round_number:  Número de ronda.
        end_number:    Número de tanda dentro de la ronda.

    Returns:
        int — cantidad de flechas en esa tanda; 0 si no hay ninguna.
    """
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM scores
        WHERE archer_id = ? AND tournament_id = ?
          AND round_number = ? AND end_number = ?
        """,
        (archer_id, tournament_id, round_number, end_number),
    )
    row = cursor.fetchone()
    return int(row["cnt"]) if row else 0
