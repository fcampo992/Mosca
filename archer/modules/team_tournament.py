"""
team_tournament.py — lógica de negocio para torneos por equipos.

Tablas involucradas:
    team_tournaments  — definición del torneo
    teams             — equipos dentro del torneo (Equipo 1, 2, 3…)
    team_members      — relación arquero ↔ equipo
    team_scores       — flechas registradas por arqueros en este tipo de torneo
"""

import random
import uuid

from archer.db import get_connection


# ---------------------------------------------------------------------------
# Torneos por equipos
# ---------------------------------------------------------------------------

def create_team_tournament(name: str, date: str, arrows_per_end: int,
                           ends_per_round: int, rounds_count: int,
                           archers_per_team: int) -> dict:
    """Crea un torneo por equipos en estado 'created'."""
    if not name or not name.strip():
        return {"error": "El nombre del torneo es obligatorio."}
    if archers_per_team < 2:
        return {"error": "El equipo debe tener al menos 2 arqueros."}
    if arrows_per_end < 1 or ends_per_round < 1 or rounds_count < 1:
        return {"error": "Flechas, tandas y rondas deben ser mayores a 0."}

    conn = get_connection()
    tid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO team_tournaments
            (id, name, date, status, arrows_per_end, ends_per_round, rounds_count, archers_per_team)
        VALUES (?, ?, ?, 'created', ?, ?, ?, ?)
        """,
        (tid, name.strip(), date, arrows_per_end, ends_per_round, rounds_count, archers_per_team),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"id": tid, "name": name.strip()}


def list_team_tournaments() -> list[dict]:
    """Retorna todos los torneos por equipos ordenados por fecha desc."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM team_tournaments ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_team_tournament(tournament_id: str) -> dict | None:
    """Retorna un torneo por equipos o None si no existe."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM team_tournaments WHERE id = ?", (tournament_id,)
    ).fetchone()
    return dict(row) if row else None


def change_team_tournament_status(tournament_id: str, new_status: str) -> dict:
    """Cambia el estado del torneo (created→active→finished)."""
    valid = ("created", "active", "finished")
    if new_status not in valid:
        return {"error": f"Estado inválido: {new_status}"}

    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}

    transitions = {"created": "active", "active": "finished"}
    if transitions.get(t["status"]) != new_status:
        return {"error": f"No se puede pasar de '{t['status']}' a '{new_status}'."}

    conn = get_connection()
    conn.execute(
        "UPDATE team_tournaments SET status = ? WHERE id = ?",
        (new_status, tournament_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


def delete_team_tournament(tournament_id: str) -> dict:
    """Elimina un torneo por equipos solo si está en estado 'created'."""
    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}
    if t["status"] != "created":
        return {"error": "Solo se pueden eliminar torneos en estado 'creado'."}

    conn = get_connection()
    # Borrar en cascada manual
    teams = conn.execute(
        "SELECT id FROM teams WHERE team_tournament_id = ?", (tournament_id,)
    ).fetchall()
    for team in teams:
        conn.execute("DELETE FROM team_members WHERE team_id = ?", (team["id"],))
    conn.execute("DELETE FROM teams WHERE team_tournament_id = ?", (tournament_id,))
    conn.execute("DELETE FROM team_scores WHERE team_tournament_id = ?", (tournament_id,))
    conn.execute("DELETE FROM team_registrations WHERE team_tournament_id = ?", (tournament_id,))
    conn.execute("DELETE FROM team_tournaments WHERE id = ?", (tournament_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


# ---------------------------------------------------------------------------
# Gestión de equipos y miembros
# ---------------------------------------------------------------------------

def list_teams(tournament_id: str) -> list[dict]:
    """
    Retorna los equipos del torneo con sus miembros.
    Cada equipo: {id, number, members: [{archer_id, archer_name}]}
    """
    conn = get_connection()
    teams = conn.execute(
        "SELECT * FROM teams WHERE team_tournament_id = ? ORDER BY number ASC",
        (tournament_id,),
    ).fetchall()

    result = []
    for t in teams:
        members = conn.execute(
            """
            SELECT tm.id AS member_id, a.id AS archer_id, a.name AS archer_name
            FROM team_members tm
            JOIN archers a ON a.id = tm.archer_id
            WHERE tm.team_id = ?
            ORDER BY a.name ASC
            """,
            (t["id"],),
        ).fetchall()
        result.append({
            "id": t["id"],
            "number": t["number"],
            "name": f"Equipo {t['number']}",
            "members": [dict(m) for m in members],
        })
    return result


def list_unassigned_archers(tournament_id: str) -> list[dict]:
    """
    Retorna los arqueros inscritos en el torneo pero aún no asignados a ningún equipo.
    """
    conn = get_connection()
    # Arqueros ya asignados a algún equipo de este torneo
    assigned = conn.execute(
        """
        SELECT tm.archer_id
        FROM team_members tm
        JOIN teams t ON t.id = tm.team_id
        WHERE t.team_tournament_id = ?
        """,
        (tournament_id,),
    ).fetchall()
    assigned_ids = {r["archer_id"] for r in assigned}

    # Solo los inscritos en este torneo
    registered = conn.execute(
        """
        SELECT tr.archer_id, a.name AS archer_name
        FROM team_registrations tr
        JOIN archers a ON a.id = tr.archer_id
        WHERE tr.team_tournament_id = ?
        ORDER BY a.name ASC
        """,
        (tournament_id,),
    ).fetchall()

    return [
        {"archer_id": r["archer_id"], "archer_name": r["archer_name"]}
        for r in registered
        if r["archer_id"] not in assigned_ids
    ]


def list_registered_archers(tournament_id: str) -> list[dict]:
    """Retorna los arqueros inscritos en el torneo por equipos."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT tr.archer_id, a.name AS archer_name
        FROM team_registrations tr
        JOIN archers a ON a.id = tr.archer_id
        WHERE tr.team_tournament_id = ?
        ORDER BY a.name ASC
        """,
        (tournament_id,),
    ).fetchall()
    return [{"archer_id": r["archer_id"], "archer_name": r["archer_name"]} for r in rows]


def enroll_archer_team(tournament_id: str, archer_id: str) -> dict:
    """Inscribe un arquero en el torneo por equipos (solo si está en 'created')."""
    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}
    if t["status"] != "created":
        return {"error": "Solo se puede inscribir en torneos en estado 'creado'."}

    conn = get_connection()
    archer_row = conn.execute("SELECT id FROM archers WHERE id = ?", (archer_id,)).fetchone()
    if not archer_row:
        return {"error": "Arquero no encontrado."}

    # Verificar si ya está inscrito
    existing = conn.execute(
        "SELECT id FROM team_registrations WHERE team_tournament_id = ? AND archer_id = ?",
        (tournament_id, archer_id),
    ).fetchone()
    if existing:
        return {"error": "El arquero ya está inscrito en este torneo."}

    conn.execute(
        "INSERT INTO team_registrations (id, team_tournament_id, archer_id) VALUES (?, ?, ?)",
        (str(uuid.uuid4()), tournament_id, archer_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


def unenroll_archer_team(tournament_id: str, archer_id: str) -> dict:
    """Desinscribe un arquero del torneo por equipos y lo quita de su equipo."""
    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}
    if t["status"] != "created":
        return {"error": "No se puede desinscribir de un torneo ya iniciado."}

    conn = get_connection()
    # Quitar de equipo si estaba asignado
    conn.execute(
        """
        DELETE FROM team_members
        WHERE archer_id = ?
          AND team_id IN (SELECT id FROM teams WHERE team_tournament_id = ?)
        """,
        (archer_id, tournament_id),
    )
    # Quitar de inscriptos
    conn.execute(
        "DELETE FROM team_registrations WHERE team_tournament_id = ? AND archer_id = ?",
        (tournament_id, archer_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


def get_active_team_tournament_for_archer(archer_id: str) -> dict | None:
    """
    Retorna el torneo por equipos activo donde el arquero está inscrito,
    o None si no hay ninguno.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT tt.*
        FROM team_tournaments tt
        JOIN team_registrations tr ON tr.team_tournament_id = tt.id
        WHERE tr.archer_id = ?
          AND tt.status = 'active'
        LIMIT 1
        """,
        (archer_id,),
    ).fetchone()
    return dict(row) if row else None


def _ensure_teams_exist(tournament_id: str, count: int) -> list[dict]:
    """Crea equipos numerados del 1 al `count` si no existen aún."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT number FROM teams WHERE team_tournament_id = ? ORDER BY number",
        (tournament_id,),
    ).fetchall()
    existing_numbers = {r["number"] for r in existing}

    for n in range(1, count + 1):
        if n not in existing_numbers:
            conn.execute(
                "INSERT INTO teams (id, team_tournament_id, number) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), tournament_id, n),
            )
    try:
        conn.commit()
    except Exception:
        pass

    return conn.execute(
        "SELECT * FROM teams WHERE team_tournament_id = ? ORDER BY number",
        (tournament_id,),
    ).fetchall()


def assign_archer_to_team(tournament_id: str, archer_id: str, team_id: str) -> dict:
    """
    Asigna un arquero a un equipo.
    - Solo permitido si el torneo está en 'created'.
    - Mueve al arquero si ya estaba en otro equipo del mismo torneo.
    """
    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}
    if t["status"] != "created":
        return {"error": "No se pueden modificar equipos una vez iniciado el torneo."}

    conn = get_connection()

    # Verificar que el team_id pertenece a este torneo
    team_row = conn.execute(
        "SELECT id FROM teams WHERE id = ? AND team_tournament_id = ?",
        (team_id, tournament_id),
    ).fetchone()
    if not team_row:
        return {"error": "Equipo no encontrado en este torneo."}

    # Verificar arquero
    archer_row = conn.execute("SELECT id FROM archers WHERE id = ?", (archer_id,)).fetchone()
    if not archer_row:
        return {"error": "Arquero no encontrado."}

    # Si ya está en un equipo de este torneo, moverlo (borrar y re-insertar)
    conn.execute(
        """
        DELETE FROM team_members
        WHERE archer_id = ?
          AND team_id IN (SELECT id FROM teams WHERE team_tournament_id = ?)
        """,
        (archer_id, tournament_id),
    )

    conn.execute(
        "INSERT INTO team_members (id, team_id, archer_id) VALUES (?, ?, ?)",
        (str(uuid.uuid4()), team_id, archer_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


def remove_archer_from_teams(tournament_id: str, archer_id: str) -> dict:
    """Quita un arquero de todos los equipos del torneo (lo deja sin asignar)."""
    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}
    if t["status"] != "created":
        return {"error": "No se pueden modificar equipos una vez iniciado el torneo."}

    conn = get_connection()
    conn.execute(
        """
        DELETE FROM team_members
        WHERE archer_id = ?
          AND team_id IN (SELECT id FROM teams WHERE team_tournament_id = ?)
        """,
        (archer_id, tournament_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


def random_assign_teams(tournament_id: str) -> dict:
    """
    Distribuye aleatoriamente todos los arqueros del sistema en equipos
    de `archers_per_team` cada uno.
    - Borra asignaciones previas del torneo.
    - Borra equipos previos y los recrea.
    - Si los arqueros no son múltiplo exacto de archers_per_team,
      los equipos finales pueden tener un arquero menos (remanente distribuido).
    """
    t = get_team_tournament(tournament_id)
    if not t:
        return {"error": "Torneo no encontrado."}
    if t["status"] != "created":
        return {"error": "Solo se puede sortear en torneos en estado 'creado'."}

    conn = get_connection()
    n_per_team = t["archers_per_team"]

    # Obtener solo los arqueros INSCRITOS en este torneo
    registered = conn.execute(
        """
        SELECT tr.archer_id
        FROM team_registrations tr
        WHERE tr.team_tournament_id = ?
        ORDER BY tr.archer_id
        """,
        (tournament_id,),
    ).fetchall()
    archer_ids = [a["archer_id"] for a in registered]

    if len(archer_ids) < 2:
        return {"error": "Se necesitan al menos 2 arqueros inscritos para armar equipos."}

    # Mezclar aleatoriamente
    random.shuffle(archer_ids)

    # Calcular cantidad de equipos necesarios
    import math
    n_teams = math.ceil(len(archer_ids) / n_per_team)

    # Borrar equipos y miembros anteriores
    old_teams = conn.execute(
        "SELECT id FROM teams WHERE team_tournament_id = ?", (tournament_id,)
    ).fetchall()
    for ot in old_teams:
        conn.execute("DELETE FROM team_members WHERE team_id = ?", (ot["id"],))
    conn.execute("DELETE FROM teams WHERE team_tournament_id = ?", (tournament_id,))
    try:
        conn.commit()
    except Exception:
        pass

    # Crear equipos y asignar arqueros
    for i in range(n_teams):
        team_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO teams (id, team_tournament_id, number) VALUES (?, ?, ?)",
            (team_id, tournament_id, i + 1),
        )
        # Slice de arqueros para este equipo
        chunk = archer_ids[i * n_per_team:(i + 1) * n_per_team]
        for archer_id in chunk:
            conn.execute(
                "INSERT INTO team_members (id, team_id, archer_id) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), team_id, archer_id),
            )
    try:
        conn.commit()
    except Exception:
        pass

    return {"ok": True, "teams": n_teams, "archers": len(archer_ids)}


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

def get_archer_team(tournament_id: str, archer_id: str) -> dict | None:
    """
    Retorna el equipo al que pertenece un arquero en el torneo por equipos,
    o None si no está asignado.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT t.id AS team_id, t.number AS team_number
        FROM team_members tm
        JOIN teams t ON t.id = tm.team_id
        WHERE t.team_tournament_id = ? AND tm.archer_id = ?
        """,
        (tournament_id, archer_id),
    ).fetchone()
    if not row:
        return None
    return {"team_id": row["team_id"], "team_number": row["team_number"],
            "team_name": f"Equipo {row['team_number']}"}


def save_team_end(tournament_id: str, archer_id: str,
                  round_number: int, end_number: int,
                  arrows: list[str]) -> dict:
    """
    Guarda las flechas de una tanda para un arquero en torneo por equipos.
    Reemplaza si ya existía (re-submit por reload).
    """
    POINTS = {"X": 10, "10": 10, "9": 9, "8": 8, "7": 7,
              "6": 6, "5": 5, "4": 4, "3": 3, "2": 2, "1": 1, "M": 0}

    conn = get_connection()

    # Borrar tanda anterior si existe (idempotente)
    conn.execute(
        """
        DELETE FROM team_scores
        WHERE team_tournament_id = ? AND archer_id = ?
          AND round_number = ? AND end_number = ?
        """,
        (tournament_id, archer_id, round_number, end_number),
    )

    for val in arrows:
        pts = POINTS.get(val, 0)
        conn.execute(
            """
            INSERT INTO team_scores
                (id, team_tournament_id, archer_id, round_number, end_number, arrow_val, points)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), tournament_id, archer_id, round_number, end_number, val, pts),
        )
    try:
        conn.commit()
    except Exception:
        pass
    return {"ok": True}


def get_team_leaderboard(tournament_id: str) -> list[dict]:
    """
    Retorna el leaderboard de equipos: lista ordenada por puntaje total desc.
    [{team_number, team_name, total_points, archer_count}]
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            t.number        AS team_number,
            COUNT(DISTINCT tm.archer_id) AS archer_count,
            COALESCE(SUM(ts.points), 0) AS total_points
        FROM teams t
        LEFT JOIN team_members tm ON tm.team_id = t.id
        LEFT JOIN team_scores ts
            ON ts.archer_id = tm.archer_id
           AND ts.team_tournament_id = t.team_tournament_id
        WHERE t.team_tournament_id = ?
        GROUP BY t.id, t.number
        ORDER BY total_points DESC, t.number ASC
        """,
        (tournament_id,),
    ).fetchall()

    return [
        {
            "team_number": r["team_number"],
            "team_name": f"Equipo {r['team_number']}",
            "archer_count": r["archer_count"],
            "total_points": r["total_points"],
        }
        for r in rows
    ]


def get_archer_team_score_summary(tournament_id: str, archer_id: str) -> dict:
    """
    Retorna el estado actual del arquero en el torneo por equipos:
    puntos acumulados, ronda y tanda actuales.
    """
    conn = get_connection()
    t = get_team_tournament(tournament_id)
    if not t:
        return {}

    total = conn.execute(
        """
        SELECT COALESCE(SUM(points), 0) AS pts
        FROM team_scores
        WHERE team_tournament_id = ? AND archer_id = ?
        """,
        (tournament_id, archer_id),
    ).fetchone()

    last_row = conn.execute(
        """
        SELECT round_number, end_number, COUNT(*) AS cnt
        FROM team_scores
        WHERE team_tournament_id = ? AND archer_id = ?
        GROUP BY round_number, end_number
        ORDER BY round_number DESC, end_number DESC
        LIMIT 1
        """,
        (tournament_id, archer_id),
    ).fetchone()

    arrows_per_end = t["arrows_per_end"]
    ends_per_round = t["ends_per_round"]
    rounds_count   = t["rounds_count"]

    round_number = 1
    end_number   = 1
    tournament_done = False

    if last_row:
        lr, le, lc = last_row["round_number"], last_row["end_number"], last_row["cnt"]
        if lc >= arrows_per_end:
            if le >= ends_per_round:
                if lr >= rounds_count:
                    tournament_done = True
                    round_number, end_number = lr, le
                else:
                    round_number, end_number = lr + 1, 1
            else:
                round_number, end_number = lr, le + 1
        else:
            round_number, end_number = lr, le

    return {
        "accumulated": total["pts"] if total else 0,
        "round_number": round_number,
        "end_number": end_number,
        "tournament_done": tournament_done,
        "arrows_per_end": arrows_per_end,
        "ends_per_round": ends_per_round,
        "rounds_count": rounds_count,
    }


def get_team_ends_history(tournament_id: str, archer_id: str) -> list[dict]:
    """Historial de tandas del arquero en el torneo por equipos."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT round_number, end_number,
               GROUP_CONCAT(arrow_val, ',') AS arrows_csv,
               SUM(points) AS pts
        FROM team_scores
        WHERE team_tournament_id = ? AND archer_id = ?
        GROUP BY round_number, end_number
        ORDER BY round_number ASC, end_number ASC
        """,
        (tournament_id, archer_id),
    ).fetchall()
    return [
        {
            "round_number": r["round_number"],
            "end_number": r["end_number"],
            "arrows": r["arrows_csv"].split(",") if r["arrows_csv"] else [],
            "pts": r["pts"],
        }
        for r in rows
    ]
