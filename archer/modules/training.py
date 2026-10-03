"""
training.py — Módulo de entrenamientos independientes.

Expone:
  - create_session(archer_id, ...)      Crea y activa una sesión de entrenamiento.
  - get_session(session_id, archer_id)  Retorna una sesión (verificando pertenencia).
  - list_sessions(archer_id)            Lista sesiones del arquero, más recientes primero.
  - finish_session(session_id, archer_id) Marca la sesión como finalizada.
  - delete_session(session_id, archer_id) Elimina una sesión y sus tandas.

  - save_end(session_id, end_number, scores, note)  Persiste una tanda completa.
  - get_end(session_id, end_number)                  Retorna una tanda.
  - list_ends(session_id)                            Todas las tandas de una sesión.

  - session_stats(session_id)   KPIs en vivo de la sesión activa.
  - training_kpis(archer_id)    KPIs históricos de todos los entrenamientos.
"""

from __future__ import annotations

import json
import uuid as _uuid
from datetime import date

from archer.db import get_connection

ARROW_POINTS: dict[str, int] = {
    "X": 10, "10": 10, "9": 9, "8": 8, "7": 7,
    "6": 6,  "5": 5,  "4": 4, "3": 3, "2": 2, "1": 1, "M": 0,
}
VALID_ARROW_VALS = set(ARROW_POINTS.keys())

# Configuración de tipos de diana
TARGET_TYPES: dict[str, dict] = {
    "wa10": {
        "label": "Standard WA / 10 pts",
        "buttons": ["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"],
        "points":  {"X": 10, "10": 10, "9": 9, "8": 8, "7": 7,
                    "6": 6, "5": 5, "4": 4, "3": 3, "2": 2, "1": 1, "M": 0},
    },
    "wa6field": {
        "label": "Field WA / 6 pts",
        "buttons": ["X", "6", "5", "4", "3", "2", "1", "M"],
        "points":  {"X": 6, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2, "1": 1, "M": 0},
    },
}
DEFAULT_TARGET = "wa10"


def _normalize_distance(d: str) -> str:
    """Normaliza la distancia a formato canónico con 'm' al final.
    '18', '18m', '18M', ' 18m ' → '18m'
    """
    if not d:
        return d
    d = d.strip().lower()
    if not d.endswith("m"):
        d = d + "m"
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scores_from_json(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _row_to_session(row: dict) -> dict:
    d = dict(row)
    return d


def _row_to_end(row: dict) -> dict:
    d = dict(row)
    d["scores"] = _scores_from_json(d.get("scores_json"))
    d["total_points"] = sum(s.get("pts", 0) for s in d["scores"])
    return d


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------

def create_session(
    archer_id: str,
    mode: str,
    distance: str,
    arrows_per_end: int,
    total_ends: int | None,
    bow_setup_id: str | None = None,
    target_face: str | None = None,
    target_type: str = DEFAULT_TARGET,
    environment: str = "indoor",
    notes: str = "",
    session_date: str | None = None,
) -> dict:
    """Crea una sesión de entrenamiento. Retorna el dict de la sesión."""
    if mode not in ("scored",):
        return {"error": "Modo inválido. Solo se admite 'scored'.", "field": "mode"}
    if not distance:
        return {"error": "La distancia es obligatoria.", "field": "distance"}
    if arrows_per_end < 1 or arrows_per_end > 12:
        return {"error": "Flechas por tanda: entre 1 y 12.", "field": "arrows_per_end"}
    if target_type not in TARGET_TYPES:
        target_type = DEFAULT_TARGET

    session_id = str(_uuid.uuid4())
    today = session_date or date.today().isoformat()
    distance_norm = _normalize_distance(distance)

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO training_sessions
            (id, archer_id, bow_setup_id, mode, distance, target_face,
             target_type, environment, arrows_per_end, total_ends,
             session_date, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (session_id, archer_id, bow_setup_id or None, mode,
         distance_norm, target_face or None,
         target_type, environment, arrows_per_end, total_ends,
         today, (notes or "").strip()),
    )
    try:
        conn.commit()
    except Exception:
        pass

    return get_session(session_id, archer_id) or {"id": session_id}


def get_session(session_id: str, archer_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM training_sessions WHERE id = ? AND archer_id = ?",
        (session_id, archer_id),
    ).fetchone()
    return _row_to_session(row) if row else None


def list_sessions(archer_id: str, limit: int = 20) -> list[dict]:
    """Retorna las sesiones más recientes del arquero."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT ts.*,
               COALESCE(bs.name, '') AS setup_name,
               COUNT(te.id)          AS ends_done
        FROM training_sessions ts
        LEFT JOIN bow_setups bs ON bs.id = ts.bow_setup_id
        LEFT JOIN training_ends te ON te.session_id = ts.id
        WHERE ts.archer_id = ?
        GROUP BY ts.id
        ORDER BY ts.session_date DESC, ts.created_at DESC
        LIMIT ?
        """,
        (archer_id, limit),
    ).fetchall()
    return [_row_to_session(r) for r in rows]


def finish_session(session_id: str, archer_id: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM training_sessions WHERE id = ? AND archer_id = ?",
        (session_id, archer_id),
    ).fetchone()
    if not row:
        return {"error": "Sesión no encontrada.", "status_code": 404}
    conn.execute(
        "UPDATE training_sessions SET status = 'finished' WHERE id = ?",
        (session_id,),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def delete_session(session_id: str, archer_id: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM training_sessions WHERE id = ? AND archer_id = ?",
        (session_id, archer_id),
    ).fetchone()
    if not row:
        return {"error": "Sesión no encontrada.", "status_code": 404}
    conn.execute("DELETE FROM training_ends WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM training_sessions WHERE id = ?", (session_id,))
    # Limpiar plots asociados
    try:
        from archer.modules.plotter import delete_all_plots_for_session  # noqa: PLC0415
        delete_all_plots_for_session("training", session_id)
    except Exception:
        pass
    try:
        conn.commit()
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Tandas
# ---------------------------------------------------------------------------

def save_end(
    session_id: str,
    end_number: int,
    scores: list[str],   # lista de arrow_val: ["X", "9", "8", ...]
    note: str = "",
) -> dict:
    """Persiste una tanda. Sobreescribe si ya existía (para correcciones)."""
    # Calcular puntos
    scored = []
    total = 0
    for val in scores:
        pts = ARROW_POINTS.get(val, 0)
        scored.append({"val": val, "pts": pts})
        total += pts

    conn = get_connection()

    # Upsert: si existe la tanda la reemplaza
    existing = conn.execute(
        "SELECT id FROM training_ends WHERE session_id = ? AND end_number = ?",
        (session_id, end_number),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE training_ends SET scores_json = ?, note = ? WHERE id = ?",
            (json.dumps(scored), (note or "").strip(), existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO training_ends (id, session_id, end_number, scores_json, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(_uuid.uuid4()), session_id, end_number,
             json.dumps(scored), (note or "").strip()),
        )
    try:
        conn.commit()
    except Exception:
        pass

    return {"end_number": end_number, "scores": scored, "total_points": total}


def get_end(session_id: str, end_number: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM training_ends WHERE session_id = ? AND end_number = ?",
        (session_id, end_number),
    ).fetchone()
    return _row_to_end(row) if row else None


def list_ends(session_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM training_ends WHERE session_id = ? ORDER BY end_number ASC",
        (session_id,),
    ).fetchall()
    return [_row_to_end(r) for r in rows]


# ---------------------------------------------------------------------------
# Stats de sesión (en vivo)
# ---------------------------------------------------------------------------

def session_stats(session_id: str) -> dict:
    """KPIs en tiempo real de la sesión activa."""
    ends = list_ends(session_id)
    if not ends:
        return {
            "ends_done": 0, "total_arrows": 0,
            "total_points": 0, "avg_per_arrow": 0.0,
            "best_end": 0, "top_zone_pct": 0.0,
        }

    all_scores: list[dict] = []
    for e in ends:
        all_scores.extend(e["scores"])

    total_arrows = len(all_scores)
    total_points = sum(s["pts"] for s in all_scores)
    avg = round(total_points / total_arrows, 2) if total_arrows else 0.0
    best_end = max((e["total_points"] for e in ends), default=0)
    top_zone = sum(1 for s in all_scores if s["val"] in ("X", "10"))
    top_pct = round(top_zone / total_arrows * 100, 1) if total_arrows else 0.0

    return {
        "ends_done":     len(ends),
        "total_arrows":  total_arrows,
        "total_points":  total_points,
        "avg_per_arrow": avg,
        "best_end":      best_end,
        "top_zone_pct":  top_pct,
    }


# ---------------------------------------------------------------------------
# KPIs históricos de entrenamiento (para el dashboard)
# ---------------------------------------------------------------------------

def training_kpis(archer_id: str) -> dict:
    """KPIs globales de todos los entrenamientos finalizados del arquero."""
    conn = get_connection()

    # Sesiones y tandas
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT ts.id) AS sessions,
               COUNT(te.id)          AS total_ends
        FROM training_sessions ts
        LEFT JOIN training_ends te ON te.session_id = ts.id
        WHERE ts.archer_id = ? AND ts.status = 'finished'
        """,
        (archer_id,),
    ).fetchone()

    sessions   = row["sessions"] if row else 0
    total_ends = row["total_ends"] if row else 0

    # Flechas y puntos (desde scores_json)
    ends_rows = conn.execute(
        """
        SELECT te.scores_json
        FROM training_ends te
        JOIN training_sessions ts ON ts.id = te.session_id
        WHERE ts.archer_id = ? AND ts.status = 'finished'
        """,
        (archer_id,),
    ).fetchall()

    all_scores: list[dict] = []
    for r in ends_rows:
        all_scores.extend(_scores_from_json(r["scores_json"]))

    total_arrows = len(all_scores)
    total_points = sum(s.get("pts", 0) for s in all_scores)
    avg = round(total_points / total_arrows, 2) if total_arrows else 0.0
    top_zone = sum(1 for s in all_scores if s.get("val") in ("X", "10"))
    top_pct = round(top_zone / total_arrows * 100, 1) if total_arrows else 0.0

    return {
        "sessions_done": sessions,
        "total_ends":    total_ends,
        "total_arrows":  total_arrows,
        "avg_per_arrow": avg,
        "top_zone_pct":  top_pct,
    }


def training_trend(archer_id: str) -> list[dict]:
    """Últimas N sesiones finalizadas con avg_per_arrow y total_points para el gráfico."""
    conn = get_connection()
    sessions = conn.execute(
        """
        SELECT ts.id, ts.session_date, ts.distance
        FROM training_sessions ts
        WHERE ts.archer_id = ? AND ts.status = 'finished'
        ORDER BY ts.session_date DESC, ts.created_at DESC
        LIMIT 20
        """,
        (archer_id,),
    ).fetchall()

    result = []
    for s in sessions:
        ends_rows = conn.execute(
            "SELECT scores_json FROM training_ends WHERE session_id = ?",
            (s["id"],),
        ).fetchall()
        all_scores: list[dict] = []
        for r in ends_rows:
            all_scores.extend(_scores_from_json(r["scores_json"]))
        total = len(all_scores)
        pts = sum(sc.get("pts", 0) for sc in all_scores)
        result.append({
            "session_id":      s["id"],
            "session_date":    s["session_date"],
            "distance":        _normalize_distance(s["distance"]),
            "total_points":    pts,
            "avg_per_arrow":   round(pts / total, 2) if total else 0.0,
        })

    return result  # DESC, el template lo puede invertir para el chart


def training_trend_by_distance(archer_id: str) -> dict[str, list[dict]]:
    """
    Retorna los datos de tendencia agrupados por distancia normalizada.
    Formato: {"18m": [...sesiones ASC...], "30m": [...], ...}
    Las distancias están ordenadas de menor a mayor (numérico).
    Solo incluye distancias con al menos 1 sesión finalizada.
    """
    raw = training_trend(archer_id)   # ya normalizado, viene DESC

    grouped: dict[str, list[dict]] = {}
    for entry in reversed(raw):       # invertir a ASC para cada distancia
        dist = entry["distance"]
        grouped.setdefault(dist, []).append(entry)

    # Ordenar las distancias de menor a mayor (extraer número)
    def _dist_key(d: str) -> float:
        try:
            return float(d.replace("m", "").replace(",", "."))
        except ValueError:
            return 9999.0

    return {k: grouped[k] for k in sorted(grouped, key=_dist_key)}


def most_recent_distance(archer_id: str) -> str | None:
    """Retorna la distancia con actividad más reciente (para el chip default)."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT distance FROM training_sessions
        WHERE archer_id = ? AND status = 'finished'
        ORDER BY session_date DESC, created_at DESC
        LIMIT 1
        """,
        (archer_id,),
    ).fetchone()
    return _normalize_distance(row["distance"]) if row else None
