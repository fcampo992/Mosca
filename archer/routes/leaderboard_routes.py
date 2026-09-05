"""
archer/routes/leaderboard_routes.py

Blueprint /leaderboard — Leaderboard en vivo via SSE.

Rutas:
    GET /leaderboard/<tournament_id>         — vista HTML del leaderboard
    GET /leaderboard/<tournament_id>/stream  — endpoint SSE público (sin auth)

Requerimientos: 6.1–6.7
"""

from __future__ import annotations

from flask import Blueprint, Response, render_template, stream_with_context

from archer.modules.leaderboard import compute_leaderboard, sse_stream
from archer.db import get_connection

leaderboard_bp = Blueprint("leaderboard", __name__, url_prefix="/leaderboard")


@leaderboard_bp.route("/<tournament_id>")
def live(tournament_id: str):
    """GET — Renderiza la vista HTML del leaderboard con estado inicial."""
    from archer.modules.club import get_club_settings  # noqa: PLC0415
    leaderboard = compute_leaderboard(tournament_id)
    # Nombre del torneo
    tournament_name = tournament_id
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT name FROM tournaments WHERE id = ?", (tournament_id,)
        ).fetchone()
        if row:
            tournament_name = row["name"]
    except Exception:
        pass
    club = get_club_settings()
    return render_template(
        "leaderboard/live.html",
        tournament_id=tournament_id,
        tournament_name=tournament_name,
        leaderboard=leaderboard,
        club=club,
    )


@leaderboard_bp.route("/<tournament_id>/stream")
def stream(tournament_id: str):
    """
    GET — Endpoint SSE público: transmite actualizaciones del leaderboard.

    No requiere autenticación (Req 6.1).
    Envía estado completo al conectar (Req 6.6).
    Emite heartbeat cada 30 s (Req 6.5).
    Soporta múltiples clientes simultáneos (Req 6.7).

    Requerimientos: 6.1, 6.2, 6.5, 6.6, 6.7
    """
    def generate():
        yield from sse_stream(tournament_id)

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@leaderboard_bp.route("/<tournament_id>/archer/<archer_id>/scorecard")
def archer_scorecard(tournament_id: str, archer_id: str):
    """GET — Retorna el scorecard completo de un arquero en JSON para el drill-down."""
    from flask import jsonify  # noqa: PLC0415
    try:
        conn = get_connection()
        # Nombre del arquero
        ar = conn.execute("SELECT name FROM archers WHERE id = ?", (archer_id,)).fetchone()
        archer_name = ar["name"] if ar else archer_id

        # Config del torneo (rounds, arrows_per_end)
        t = conn.execute(
            "SELECT rounds, arrows_per_end FROM tournaments WHERE id = ?", (tournament_id,)
        ).fetchone()
        rounds = t["rounds"] if t else 10
        arrows_per_end = t["arrows_per_end"] if t else 6

        # Todas las flechas del arquero en este torneo
        cursor = conn.execute(
            """
            SELECT round_number, end_number, arrow_val, points
            FROM scores
            WHERE archer_id = ? AND tournament_id = ?
            ORDER BY round_number, end_number, created_at
            """,
            (archer_id, tournament_id),
        )
        rows = cursor.fetchall()

        # Organizar en estructura: rounds_data[round][end] = [arrows...]
        rounds_data: dict[int, dict[int, list]] = {}
        for row in rows:
            r, e = row["round_number"], row["end_number"]
            rounds_data.setdefault(r, {}).setdefault(e, []).append({
                "arrow_val": row["arrow_val"],
                "points": row["points"],
            })

        # Construir lista de rondas con totales
        result_rounds = []
        for r_num in sorted(rounds_data.keys()):
            ends = []
            round_total = 0
            for e_num in sorted(rounds_data[r_num].keys()):
                arrows = rounds_data[r_num][e_num]
                end_total = sum(a["points"] for a in arrows)
                round_total += end_total
                ends.append({
                    "end_number": e_num,
                    "arrows": arrows,
                    "end_total": end_total,
                })
            result_rounds.append({
                "round_number": r_num,
                "ends": ends,
                "round_total": round_total,
            })

        total = sum(a["points"] for row in rows for a in [{"points": row["points"]}])

        return jsonify({
            "archer_id": archer_id,
            "archer_name": archer_name,
            "tournament_id": tournament_id,
            "rounds": result_rounds,
            "total_points": total,
            "rounds_config": rounds,
            "arrows_per_end_config": arrows_per_end,
        })
    except Exception as exc:
        from flask import jsonify as _j  # noqa: PLC0415
        return _j({"error": str(exc)}), 500


@leaderboard_bp.route("/<tournament_id>/podium")
def podium(tournament_id: str):
    """
    GET — Vista de podio final con confetti y destacado de ganadores.
    Funciona para cualquier torneo (activo o finalizado).
    """
    leaderboard = compute_leaderboard(tournament_id)

    # Obtener nombre del torneo
    tournament_name = tournament_id
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT name FROM tournaments WHERE id = ?", (tournament_id,)
        ).fetchone()
        if row:
            tournament_name = row["name"]
    except Exception:
        pass

    return render_template(
        "leaderboard/podium.html",
        tournament_id=tournament_id,
        tournament_name=tournament_name,
        leaderboard=leaderboard,
    )
