"""
archer/routes/stats_routes.py

Blueprint /stats — Estadisticas de torneos, tendencia historica y ranking global.

Rutas JSON (API):
    GET /stats/tournament/<tournament_id>          — estadisticas de torneo (JSON)
    GET /stats/archer/<archer_id>/trend            — tendencia historica (JSON)
    GET /stats/ranking                             — ranking global (JSON)

Rutas HTML (vistas):
    GET /stats/tournament/<tournament_id>/view     — vista HTML de estadisticas
    GET /stats/archer/<archer_id>/trend/view       — vista HTML de tendencia historica
    GET /stats/ranking/view                        — vista HTML del ranking global

Requerimientos: 7.1-7.7, 8.1-8.4, 9.1-9.6
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from archer.modules.stats import archer_trend, global_ranking, tournament_stats

stats_bp = Blueprint("stats", __name__, url_prefix="/stats")


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

def _require_stats_access(archer_id: str) -> bool:
    """
    Retorna True si el solicitante tiene acceso a las stats del archer_id dado.

    Reglas:
    - Admin autenticado (session["admin_logged_in"]) -> acceso a todo.
    - Arquero autenticado (session["archer_id"]) -> solo sus propios datos.
    - Sin sesion -> sin acceso.
    """
    if session.get("admin_logged_in"):
        return True
    return session.get("archer_id") == archer_id


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------

@stats_bp.route("/tournament/<tournament_id>")
def tournament(tournament_id: str):
    """
    GET — Retorna estadisticas del torneo en formato JSON.

    Query param opcional: ?archer_id=<uuid> para filtrar a un arquero especifico.

    Requerimientos: 7.1-7.7
    """
    archer_id = request.args.get("archer_id") or None

    result = tournament_stats(tournament_id, archer_id=archer_id)

    if "status_code" in result:
        status_code = result.pop("status_code")
        return jsonify(result), status_code

    return jsonify(result), 200


@stats_bp.route("/archer/<archer_id>/trend")
def trend(archer_id: str):
    """
    GET — Retorna la tendencia historica del arquero en formato JSON.

    Devuelve arreglo vacio si no hay torneos finished (Req 8.3).
    Retorna 403 si el solicitante no tiene acceso a los datos del arquero (Req 2.11).

    Requerimientos: 8.1-8.4, 2.11
    """
    if not _require_stats_access(archer_id):
        return jsonify({"error": "Acceso no autorizado."}), 403
    result = archer_trend(archer_id)
    return jsonify(result), 200


@stats_bp.route("/ranking")
def ranking():
    """
    GET — Redirige a la vista HTML del ranking global.
    El endpoint JSON está disponible en /stats/ranking/data para uso de API.

    Requerimientos: 9.1-9.6
    """
    return redirect(url_for("stats.ranking_view"))


@stats_bp.route("/ranking/data")
def ranking_data():
    """
    GET — Retorna el ranking global en formato JSON (endpoint de API).

    Retorna HTTP 503 si la DB no está disponible (Req 9.6).

    Requerimientos: 9.1-9.6
    """
    try:
        result = global_ranking()
    except Exception:
        return jsonify({"error": "Servicio no disponible temporalmente"}), 503

    return jsonify(result), 200


# ---------------------------------------------------------------------------
# HTML view endpoints
# ---------------------------------------------------------------------------

@stats_bp.route("/tournament/<tournament_id>/view")
def tournament_view(tournament_id: str):
    """Vista HTML de estadisticas del torneo. Requerimientos: 7.1-7.7, 10.4"""
    archer_id = request.args.get("archer_id") or None
    result = tournament_stats(tournament_id, archer_id=archer_id)
    if "status_code" in result:
        return render_template("stats/tournament.html", data=None), result["status_code"]
    return render_template("stats/tournament.html", data=result)


@stats_bp.route("/archer/<archer_id>/trend/view")
def trend_view(archer_id: str):
    """Vista HTML de tendencia histórica del arquero. Requerimientos: 8.1-8.4, 10.4"""
    if not _require_stats_access(archer_id):
        return redirect(url_for("archer.login"))
    result = archer_trend(archer_id)

    # Obtener nombre y foto del arquero para el encabezado
    archer_name = ""
    archer_photo = ""
    try:
        from archer.db import get_connection  # noqa: PLC0415
        conn = get_connection()
        row = conn.execute(
            "SELECT name, photo_url FROM archers WHERE id = ?", (archer_id,)
        ).fetchone()
        if row:
            archer_name  = row["name"]
            archer_photo = row["photo_url"] or ""
    except Exception:
        pass

    return render_template("stats/trend.html",
                           trend=result,
                           archer_name=archer_name,
                           archer_photo=archer_photo)


@stats_bp.route("/ranking/view")
def ranking_view():
    """Vista HTML del ranking global. Requerimientos: 9.1-9.6, 10.4"""
    try:
        result = global_ranking()
    except Exception:
        result = []
    return render_template("stats/ranking.html", ranking=result)

