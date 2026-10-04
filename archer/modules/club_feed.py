"""
club_feed.py — Datos para la sección "Club" del arquero autenticado.

Expone:
  - get_active_tournaments_ranking()   Rankings de torneos activos (en curso)
  - get_global_ranking(limit)          Ranking histórico global (torneos finalizados)
  - get_activity_feed(limit)           Feed de actividad reciente del club
"""

from __future__ import annotations
from archer.db import get_connection


def get_active_tournaments_ranking() -> list[dict]:
    """
    Retorna ranking en tiempo real de los torneos activos.
    Para cada torneo activo: lista de arqueros con total acumulado hasta el momento.
    """
    conn = get_connection()
    tournaments = conn.execute(
        "SELECT id, name FROM tournaments WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall()

    result = []
    for t in tournaments:
        rows = conn.execute(
            """
            SELECT a.id AS archer_id, a.name AS archer_name,
                   COALESCE(SUM(s.points), 0) AS total_points,
                   COUNT(s.id) AS total_arrows
            FROM registrations r
            JOIN archers a ON a.id = r.archer_id
            LEFT JOIN scores s ON s.archer_id = r.archer_id AND s.tournament_id = r.tournament_id
            WHERE r.tournament_id = ?
            GROUP BY a.id, a.name
            ORDER BY total_points DESC, a.name ASC
            """,
            (t["id"],),
        ).fetchall()

        entries = []
        for i, row in enumerate(rows):
            entries.append({
                "position":      i + 1,
                "archer_id":     row["archer_id"],
                "archer_name":   row["archer_name"],
                "total_points":  row["total_points"],
                "total_arrows":  row["total_arrows"],
            })

        result.append({
            "tournament_id":   t["id"],
            "tournament_name": t["name"],
            "entries":         entries,
        })

    return result


def get_global_ranking(limit: int = 20) -> list[dict]:
    """
    Ranking global acumulado basado en torneos finalizados.
    Retorna los primeros `limit` arqueros.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT a.id AS archer_id, a.name AS archer_name,
               COALESCE(SUM(s.points), 0) AS total_points,
               COUNT(DISTINCT t.id)       AS tournaments_played
        FROM archers a
        LEFT JOIN registrations r ON r.archer_id = a.id
        LEFT JOIN tournaments t ON t.id = r.tournament_id AND t.status = 'finished'
        LEFT JOIN scores s ON s.archer_id = a.id AND s.tournament_id = t.id
        GROUP BY a.id, a.name
        ORDER BY total_points DESC, a.name ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    result = []
    for i, row in enumerate(rows):
        result.append({
            "position":           i + 1,
            "archer_id":          row["archer_id"],
            "archer_name":        row["archer_name"],
            "total_points":       row["total_points"],
            "tournaments_played": row["tournaments_played"],
        })
    return result


def get_activity_feed(limit: int = 20) -> list[dict]:
    """
    Feed de actividad reciente del club.
    Combina eventos de distintas fuentes y los devuelve ordenados por fecha desc.

    Tipos de evento:
      - 'tournament_started'   → un torneo pasó a activo
      - 'tournament_finished'  → un torneo finalizó
      - 'score_end'            → un arquero completó una tanda en torneo
      - 'training_done'        → un arquero terminó una sesión de entrenamiento
    """
    conn = get_connection()
    events: list[dict] = []

    # ── Torneos que empezaron o terminaron (últimos 30 días) ──────────────
    t_rows = conn.execute(
        """
        SELECT id, name, status, created_at
        FROM tournaments
        WHERE status IN ('active', 'finished')
        ORDER BY created_at DESC
        LIMIT 10
        """
    ).fetchall()

    for t in t_rows:
        event_type = 'tournament_started' if t["status"] == 'active' else 'tournament_finished'
        events.append({
            "type":     event_type,
            "ts":       t["created_at"] or "",
            "title":    t["name"],
            "subtitle": "Torneo iniciado" if event_type == 'tournament_started' else "Torneo finalizado",
            "icon":     "🟢" if event_type == 'tournament_started' else "🏆",
            "extra":    {"tournament_id": t["id"]},
        })

    # ── Últimas tandas completadas en torneos (agrupadas por arquero+ronda) ──
    score_rows = conn.execute(
        """
        SELECT a.name AS archer_name, t.name AS tournament_name,
               s.round_number, SUM(s.points) AS round_pts,
               MAX(s.created_at) AS ts
        FROM scores s
        JOIN archers a ON a.id = s.archer_id
        JOIN tournaments t ON t.id = s.tournament_id
        WHERE t.status = 'active'
        GROUP BY s.archer_id, s.tournament_id, s.round_number, s.end_number
        ORDER BY ts DESC
        LIMIT 15
        """
    ).fetchall()

    for row in score_rows:
        pts = row["round_pts"] or 0
        events.append({
            "type":     "score_end",
            "ts":       row["ts"] or "",
            "title":    row["archer_name"],
            "subtitle": f"{pts} pts en {row['tournament_name']}",
            "icon":     "🎯",
            "extra":    {},
        })

    # ── Últimas sesiones de entrenamiento finalizadas ─────────────────────
    train_rows = conn.execute(
        """
        SELECT a.name AS archer_name, ts.distance, ts.session_date,
               ts.created_at AS ts,
               COUNT(te.id) AS ends_done,
               COALESCE(SUM(
                   CASE WHEN te.scores_json != '[]' THEN 1 ELSE 0 END
               ), 0) AS scored_ends
        FROM training_sessions ts
        JOIN archers a ON a.id = ts.archer_id
        LEFT JOIN training_ends te ON te.session_id = ts.id
        WHERE ts.status = 'finished'
        GROUP BY ts.id
        ORDER BY ts.created_at DESC
        LIMIT 10
        """
    ).fetchall()

    for row in train_rows:
        events.append({
            "type":     "training_done",
            "ts":       row["ts"] or "",
            "title":    row["archer_name"],
            "subtitle": f"Entrenamiento {row['distance']} · {row['ends_done']} tandas",
            "icon":     "🏹",
            "extra":    {},
        })

    # ── Ordenar por timestamp descendente ────────────────────────────────
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:limit]
