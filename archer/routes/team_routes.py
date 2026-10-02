"""
team_routes.py — rutas admin y arquero para torneos por equipos.

Blueprints:
    team_admin_bp  — /admin/team-tournaments/…
    team_archer_bp — /team/…  (score del arquero en torneo por equipos)
"""

from __future__ import annotations

import json
import logging

from flask import (
    Blueprint, redirect, render_template, request,
    session, url_for, jsonify,
)

from archer.modules.team_tournament import (
    assign_archer_to_team,
    change_team_tournament_status,
    create_team_tournament,
    delete_team_tournament,
    enroll_archer_team,
    unenroll_archer_team,
    get_archer_team,
    get_archer_team_score_summary,
    get_team_ends_history,
    get_team_leaderboard,
    get_team_tournament,
    list_registered_archers,
    list_team_tournaments,
    list_teams,
    list_unassigned_archers,
    random_assign_teams,
    remove_archer_from_teams,
    save_team_end,
)
from archer.modules.admin import list_archers  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers de autenticación
# ---------------------------------------------------------------------------

def _require_admin(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return fn(*args, **kwargs)
    return wrapper


def _require_archer_session(fn):
    from functools import wraps
    from archer.modules.archer import is_session_valid  # type: ignore
    @wraps(fn)
    def wrapper(*args, **kwargs):
        archer_id   = session.get("archer_id")
        last_active = session.get("last_active", "")
        if not archer_id or not is_session_valid(last_active):
            session.clear()
            return redirect(url_for("archer.login"))
        from datetime import datetime
        session["last_active"] = datetime.now().isoformat()
        return fn(*args, **kwargs)
    return wrapper


# ===========================================================================
# Admin blueprint
# ===========================================================================

team_admin_bp = Blueprint("team_admin", __name__, url_prefix="/admin/team-tournaments")


@team_admin_bp.route("/", methods=["GET"])
@_require_admin
def index():
    """Lista todos los torneos por equipos."""
    tournaments = list_team_tournaments()
    return render_template("admin/team_tournaments.html", tournaments=tournaments)


@team_admin_bp.route("/new", methods=["GET", "POST"])
@_require_admin
def new():
    """Formulario para crear un torneo por equipos."""
    if request.method == "GET":
        return render_template("admin/team_tournament_new.html", error=None, form_data={})

    name             = request.form.get("name", "").strip()
    date             = request.form.get("date", "").strip()
    arrows_per_end   = int(request.form.get("arrows_per_end", 6))
    ends_per_round   = int(request.form.get("ends_per_round", 10))
    rounds_count     = int(request.form.get("rounds_count", 1))
    archers_per_team = int(request.form.get("archers_per_team", 3))

    result = create_team_tournament(
        name, date, arrows_per_end, ends_per_round, rounds_count, archers_per_team
    )

    if "error" in result:
        return render_template(
            "admin/team_tournament_new.html",
            error=result["error"],
            form_data=request.form,
        ), 400

    return redirect(url_for("team_admin.detail", tournament_id=result["id"]))


@team_admin_bp.route("/<tournament_id>", methods=["GET"])
@_require_admin
def detail(tournament_id: str):
    """Detalle del torneo: info + gestión de equipos."""
    tournament = get_team_tournament(tournament_id)
    if not tournament:
        return redirect(url_for("team_admin.index"))

    teams           = list_teams(tournament_id)
    registered      = list_registered_archers(tournament_id)
    unassigned      = list_unassigned_archers(tournament_id)
    all_archers     = list_archers()
    registered_ids  = {a["archer_id"] for a in registered}

    return render_template(
        "admin/team_tournament_detail.html",
        tournament=tournament,
        teams=teams,
        registered=registered,
        registered_ids=registered_ids,
        unassigned=unassigned,
        all_archers=all_archers,
        unenroll_error=request.args.get("error"),
    )


@team_admin_bp.route("/<tournament_id>/enroll", methods=["POST"])
@_require_admin
def enroll(tournament_id: str):
    """Inscribe un arquero en el torneo por equipos."""
    archer_id = request.form.get("archer_id", "").strip()
    result = enroll_archer_team(tournament_id, archer_id)
    if "error" in result:
        return redirect(url_for("team_admin.detail", tournament_id=tournament_id,
                                error=result["error"]))
    return redirect(url_for("team_admin.detail", tournament_id=tournament_id))


@team_admin_bp.route("/<tournament_id>/unenroll", methods=["POST"])
@_require_admin
def unenroll(tournament_id: str):
    """Desinscribe un arquero del torneo por equipos."""
    archer_id = request.form.get("archer_id", "").strip()
    unenroll_archer_team(tournament_id, archer_id)
    return redirect(url_for("team_admin.detail", tournament_id=tournament_id))


@team_admin_bp.route("/<tournament_id>/status", methods=["POST"])
@_require_admin
def status(tournament_id: str):
    """Cambia el estado del torneo."""
    new_status = request.form.get("new_status", "").strip()
    result = change_team_tournament_status(tournament_id, new_status)
    if "error" in result:
        logger.warning("status change error: %s", result["error"])
    return redirect(url_for("team_admin.detail", tournament_id=tournament_id))


@team_admin_bp.route("/<tournament_id>/delete", methods=["POST"])
@_require_admin
def delete(tournament_id: str):
    """Elimina el torneo (solo si está en 'created')."""
    delete_team_tournament(tournament_id)
    return redirect(url_for("team_admin.index"))


@team_admin_bp.route("/<tournament_id>/assign", methods=["POST"])
@_require_admin
def assign(tournament_id: str):
    """Asigna un arquero a un equipo (mover entre equipos o desde sin-asignar)."""
    archer_id = request.form.get("archer_id", "").strip()
    team_id   = request.form.get("team_id", "").strip()

    result = assign_archer_to_team(tournament_id, archer_id, team_id)
    if "error" in result:
        return redirect(url_for("team_admin.detail", tournament_id=tournament_id,
                                error=result["error"]))
    return redirect(url_for("team_admin.detail", tournament_id=tournament_id))


@team_admin_bp.route("/<tournament_id>/unassign", methods=["POST"])
@_require_admin
def unassign(tournament_id: str):
    """Quita un arquero de su equipo (lo deja sin asignar)."""
    archer_id = request.form.get("archer_id", "").strip()
    remove_archer_from_teams(tournament_id, archer_id)
    return redirect(url_for("team_admin.detail", tournament_id=tournament_id))


@team_admin_bp.route("/<tournament_id>/random", methods=["POST"])
@_require_admin
def random_teams(tournament_id: str):
    """Sorteo aleatorio de equipos."""
    result = random_assign_teams(tournament_id)
    if "error" in result:
        return redirect(url_for("team_admin.detail", tournament_id=tournament_id,
                                error=result["error"]))
    return redirect(url_for("team_admin.detail", tournament_id=tournament_id))


@team_admin_bp.route("/<tournament_id>/leaderboard", methods=["GET"])
def leaderboard(tournament_id: str):
    """Tabla de clasificación pública de equipos."""
    tournament = get_team_tournament(tournament_id)
    if not tournament:
        return redirect(url_for("team_admin.index"))

    teams_lb = get_team_leaderboard(tournament_id)
    return render_template(
        "team_leaderboard.html",
        tournament=tournament,
        teams=teams_lb,
    )


# ===========================================================================
# Archer blueprint — score de torneo por equipos
# ===========================================================================

team_archer_bp = Blueprint("team_archer", __name__, url_prefix="/team")


@team_archer_bp.route("/score/<tournament_id>", methods=["GET"])
@_require_archer_session
def score(tournament_id: str):
    """Vista del teclado táctil para torneo por equipos."""
    from archer.modules.club import get_club_settings  # noqa: PLC0415
    from archer.modules.training import TARGET_TYPES, DEFAULT_TARGET  # noqa: PLC0415

    archer_id   = session["archer_id"]
    archer_name = session.get("archer_name", "Arquero")
    club        = get_club_settings()

    tournament = get_team_tournament(tournament_id)
    if not tournament:
        return redirect(url_for("archer.dashboard"))

    team_info = get_archer_team(tournament_id, archer_id)
    summary   = get_archer_team_score_summary(tournament_id, archer_id)
    history   = get_team_ends_history(tournament_id, archer_id)

    photo_url = session.get("photo_url")

    target_type = tournament.get("target_type") or DEFAULT_TARGET
    target_cfg  = TARGET_TYPES.get(target_type, TARGET_TYPES[DEFAULT_TARGET])

    return render_template(
        "archer/team_score.html",
        club=club,
        tournament=tournament,
        team_info=team_info,
        archer_name=archer_name,
        photo_url=photo_url,
        accumulated=summary.get("accumulated", 0),
        round_number=summary.get("round_number", 1),
        end_number=summary.get("end_number", 1),
        tournament_done=summary.get("tournament_done", False),
        arrows_per_end=summary.get("arrows_per_end", tournament["arrows_per_end"]),
        ends_history=history,
        target_type=target_type,
        target_cfg=target_cfg,
    )


@team_archer_bp.route("/score/<tournament_id>/end", methods=["POST"])
@_require_archer_session
def score_end(tournament_id: str):
    """Recibe y guarda una tanda del arquero en torneo por equipos."""
    archer_id = session["archer_id"]
    summary   = get_archer_team_score_summary(tournament_id, archer_id)

    arrows_json = request.form.get("arrows_json", "[]")
    try:
        arrows = json.loads(arrows_json)
    except Exception:
        arrows = []

    save_team_end(
        tournament_id, archer_id,
        summary.get("round_number", 1),
        summary.get("end_number", 1),
        arrows,
    )
    return ("", 204)
