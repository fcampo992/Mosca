"""
archer/routes/admin_routes.py

Blueprint /admin — Panel de administración de torneos, categorías y arqueros.

Rutas:
    GET  /admin/tournaments                    — listar torneos
    POST /admin/tournaments                    — crear torneo
    POST /admin/tournaments/<id>/status        — cambiar estado del torneo
    GET  /admin/tournaments/<id>/categories    — listar categorías del torneo
    POST /admin/tournaments/<id>/categories    — crear categoría en el torneo
    GET  /admin/archers                        — listar arqueros
    POST /admin/archers                        — crear arquero
    POST /admin/archers/<id>/enroll            — inscribir arquero en torneo/categoría

Requerimientos: 2.1–2.9, 3.1–3.9
"""

from __future__ import annotations

import functools
import logging

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from archer.modules.admin import (
    change_tournament_status,
    correct_arrow_admin,
    create_archer,
    create_category,
    create_tournament,
    delete_archer,
    delete_tournament,
    enroll_archer,
    get_tournament,
    list_archers,
    list_categories,
    list_enrolled_archers,
    list_tournaments,
    update_archer,
)
from archer.modules.club import get_club_settings, save_club_settings
from archer.modules.news import create_news, delete_news, list_news, toggle_news

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def require_admin(view):
    """Decorador: redirige a /admin/login si no hay sesión de admin activa."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped

# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    GET  — Renderiza el formulario de login. Si ya hay sesión, redirige a torneos.
    POST — Valida credenciales contra ADMIN_USERNAME y ADMIN_PASSWORD de config.
           Si son correctas, establece sesión y redirige a torneos.
           Si son incorrectas, re-renderiza con error 401 (sin incluir la contraseña en logs).

    Requerimientos: 2.4, 2.5
    """
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.tournaments"))

    if request.method == "GET":
        return render_template("admin/login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    cfg = current_app.config
    if username == cfg["ADMIN_USERNAME"] and password == cfg["ADMIN_PASSWORD"]:
        session["admin_logged_in"] = True
        session["admin_username"] = username
        return redirect(url_for("admin.tournaments"))

    logger.warning("Admin login failed for username=%s", username)
    return render_template("admin/login.html", error="Credenciales incorrectas."), 401


@admin_bp.route("/logout", methods=["POST"])
def logout():
    """
    POST — Cierra la sesión administrativa.

    Elimina las claves de sesión admin y redirige al formulario de login.

    Requerimientos: 2.3
    """
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_code_from_error(result: dict, default: int = 400) -> int:
    """Extrae el código HTTP de un dict de error, o usa el valor por defecto."""
    return result.get("status_code", default)


# ---------------------------------------------------------------------------
# Torneos
# ---------------------------------------------------------------------------

@admin_bp.route("/tournaments", methods=["GET", "POST"])
@require_admin
def tournaments():
    """
    GET  — Renderiza la lista de torneos junto con el formulario de creación.
    POST — Crea un nuevo torneo; si hay error re-renderiza el formulario con
           el mensaje de error; si tiene éxito redirige a la misma vista.

    Requerimientos: 2.1, 2.2, 2.9
    """
    error = None
    field = None
    form_data: dict = {}

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        date = request.form.get("date", "").strip()
        rounds = request.form.get("rounds", "10").strip()
        arrows_per_end = request.form.get("arrows_per_end", "5").strip()
        rounds_count = request.form.get("rounds_count", "1").strip()
        form_data = {"name": name, "date": date, "rounds": rounds, "arrows_per_end": arrows_per_end, "rounds_count": rounds_count}

        result = create_tournament(name, date, rounds=rounds, arrows_per_end=arrows_per_end, rounds_count=rounds_count)

        if "error" in result:
            error = result["error"]
            field = result.get("field")
            status_code = _status_code_from_error(result)
            return (
                render_template(
                    "admin/tournaments.html",
                    tournaments=list_tournaments(),
                    error=error,
                    field=field,
                    form_data=form_data,
                ),
                status_code,
            )

        # Éxito → redirigir (POST-Redirect-GET)
        return redirect(url_for("admin.tournaments"))

    # GET
    return render_template(
        "admin/tournaments.html",
        tournaments=list_tournaments(),
        error=error,
        field=field,
        form_data=form_data,
    )


@admin_bp.route("/tournaments/<tournament_id>/status", methods=["POST"])
@require_admin
def tournament_status(tournament_id: str):
    """
    POST — Cambia el estado de un torneo.

    Espera el campo de formulario 'new_status'.
    Si hay error re-renderiza la lista de torneos con el mensaje de error.
    Si tiene éxito redirige al listado de torneos.

    Requerimientos: 2.6, 2.7, 2.8
    """
    new_status = request.form.get("new_status", "").strip()
    result = change_tournament_status(tournament_id, new_status)

    if "error" in result:
        status_code = _status_code_from_error(result, default=422)
        return (
            render_template(
                "admin/tournaments.html",
                tournaments=list_tournaments(),
                error=result["error"],
                field=None,
                form_data={},
            ),
            status_code,
        )

    return redirect(url_for("admin.tournament_detail", tournament_id=tournament_id))


@admin_bp.route("/tournaments/<tournament_id>/delete", methods=["POST"])
@require_admin
def delete_tournament_route(tournament_id: str):
    """
    POST — Elimina un torneo en estado 'created' junto con sus categorías y
           registraciones asociadas (cascada manual).

    Si el torneo no existe o no está en estado 'created', re-renderiza
    admin/tournaments.html con el mensaje de error y el status code apropiado.
    Si tiene éxito redirige al listado de torneos.

    Requerimientos: 2.8
    """
    result = delete_tournament(tournament_id)
    if "error" in result:
        status_code = result.get("status_code", 400)
        return render_template(
            "admin/tournaments.html",
            tournaments=list_tournaments(),
            error=result["error"],
            field=None,
            form_data={},
        ), status_code
    return redirect(url_for("admin.tournaments"))


# ---------------------------------------------------------------------------
# Detalle del torneo (vista con tabs)
# ---------------------------------------------------------------------------

@admin_bp.route("/tournaments/<tournament_id>", methods=["GET"])
@require_admin
def tournament_detail(tournament_id: str):
    """
    GET — Vista de detalle del torneo con tabs: Categorías, Arqueros, Acciones.
    Centraliza toda la gestión de un torneo en una sola pantalla.
    """
    tournament = get_tournament(tournament_id)
    if tournament is None:
        return redirect(url_for("admin.tournaments"))
    categories_list = list_categories(tournament_id)
    archers_list = list_enrolled_archers(tournament_id)
    return render_template(
        "admin/tournament_detail.html",
        tournament=tournament,
        categories=categories_list,
        archers=archers_list,
        error=None,
        field=None,
        form_data={},
    )


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------

@admin_bp.route("/tournaments/<tournament_id>/categories", methods=["GET", "POST"])
@require_admin
def categories(tournament_id: str):
    """
    GET  — Renderiza las categorías del torneo junto con el formulario de creación.
    POST — Crea una nueva categoría; si hay error re-renderiza el formulario
           con el mensaje de error; si tiene éxito redirige a la misma vista.

    Requerimientos: 2.3, 2.4, 2.5
    """
    error = None
    field = None
    form_data: dict = {}

    if request.method == "POST":
        bow_type = request.form.get("bow_type", "").strip()
        distance = request.form.get("distance", "").strip()
        gender = request.form.get("gender", "").strip()
        form_data = {"bow_type": bow_type, "distance": distance, "gender": gender}

        result = create_category(tournament_id, bow_type, distance, gender)

        if "error" in result:
            error = result["error"]
            field = result.get("field")
            status_code = _status_code_from_error(result)
            return (
                render_template(
                    "admin/categories.html",
                    tournament_id=tournament_id,
                    categories=list_categories(tournament_id),
                    error=error,
                    field=field,
                    form_data=form_data,
                ),
                status_code,
            )

        # Éxito → redirigir al detalle del torneo
        return redirect(url_for("admin.tournament_detail", tournament_id=tournament_id))

    # GET
    return render_template(
        "admin/categories.html",
        tournament_id=tournament_id,
        categories=list_categories(tournament_id),
        error=error,
        field=field,
        form_data=form_data,
    )


# ---------------------------------------------------------------------------
# Arqueros
# ---------------------------------------------------------------------------

@admin_bp.route("/archers", methods=["GET", "POST"])
@require_admin
def archers():
    """
    GET  — Renderiza la lista de arqueros junto con el formulario de creación.
    POST — Crea un nuevo arquero; si hay error re-renderiza el formulario con
           el mensaje de error; si tiene éxito redirige a la misma vista.

    Requerimientos: 3.1, 3.2, 3.3, 3.4, 3.9
    """
    error = None
    field = None
    form_data: dict = {}

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pin = request.form.get("pin", "").strip()
        form_data = {"name": name, "pin": pin}

        result = create_archer(name, pin)

        if "error" in result:
            error = result["error"]
            field = result.get("field")
            status_code = _status_code_from_error(result)
            return (
                render_template(
                    "admin/archers.html",
                    archers=list_archers(),
                    tournaments=list_tournaments(),
                    error=error,
                    field=field,
                    form_data=form_data,
                    enroll_error=None,
                ),
                status_code,
            )

        # Éxito → redirigir (POST-Redirect-GET)
        return redirect(url_for("admin.archers"))

    # GET
    return render_template(
        "admin/archers.html",
        archers=list_archers(),
        tournaments=list_tournaments(),
        error=error,
        field=field,
        form_data=form_data,
        enroll_error=None,
    )


@admin_bp.route("/archers/<archer_id>/enroll", methods=["POST"])
@require_admin
def enroll(archer_id: str):
    """
    POST — Inscribe un arquero en un torneo/categoría.

    Espera los campos de formulario 'tournament_id' y 'category_id'.
    Si hay error re-renderiza la vista de arqueros con el mensaje de error.
    Si tiene éxito redirige al listado de arqueros.

    Requerimientos: 3.5, 3.6, 3.7, 3.8
    """
    tournament_id = request.form.get("tournament_id", "").strip()
    category_id = request.form.get("category_id", "").strip()

    result = enroll_archer(archer_id, tournament_id, category_id)

    if "error" in result:
        status_code = _status_code_from_error(result)
        return (
            render_template(
                "admin/archers.html",
                archers=list_archers(),
                tournaments=list_tournaments(),
                error=None,
                field=None,
                form_data={},
                enroll_error=result["error"],
                enroll_archer_id=archer_id,
            ),
            status_code,
        )

    return redirect(url_for("admin.archers"))


@admin_bp.route("/archers/<archer_id>/delete", methods=["POST"])
@require_admin
def delete_archer_route(archer_id: str):
    """
    POST — Elimina un arquero si no tiene inscripciones en torneos activos o finalizados.

    Si hay error re-renderiza la vista de arqueros con el mensaje de error.
    Si tiene éxito redirige al listado de arqueros.

    Requerimientos: 2.9
    """
    result = delete_archer(archer_id)
    if "error" in result:
        status_code = result.get("status_code", 400)
        return render_template(
            "admin/archers.html",
            archers=list_archers(),
            tournaments=list_tournaments(),
            error=result["error"],
            field=None,
            form_data={},
            enroll_error=None,
        ), status_code
    return redirect(url_for("admin.archers"))


@admin_bp.route("/tournaments/<tournament_id>/categories/json", methods=["GET"])
@require_admin
def categories_json(tournament_id: str):
    """GET — retorna las categorías del torneo como JSON para el select dinámico."""
    cats = list_categories(tournament_id)
    return jsonify(cats)


# ---------------------------------------------------------------------------
# Arqueros inscritos en un torneo
# ---------------------------------------------------------------------------

@admin_bp.route("/tournaments/<tournament_id>/archers", methods=["GET"])
@require_admin
def enrolled_archers(tournament_id: str):
    """
    GET — Muestra la lista de arqueros inscritos en el torneo indicado.

    Renderiza admin/enrolled_archers.html con:
      - tournament: dict del torneo (o None si no existe)
      - archers:    lista de dicts con archer_id, archer_name, category

    Requerimientos: 2.7
    """
    archers = list_enrolled_archers(tournament_id)
    tournament = get_tournament(tournament_id)
    return render_template(
        "admin/enrolled_archers.html",
        tournament=tournament,
        archers=archers,
    )


# ---------------------------------------------------------------------------
# Corrección de flechas (Requerimientos 4.1, 4.2, 4.3, 4.4)
# ---------------------------------------------------------------------------

@admin_bp.route("/scores/correct", methods=["POST"])
@require_admin
def correct_score():
    """
    POST — Corrige el valor de una flecha por su score_id.

    El administrador puede corregir cualquier flecha independientemente de la
    ronda o tanda a la que pertenezca.

    Espera los campos de formulario 'score_id', 'arrow_val' y 'redirect_to'.
    Si hay error re-renderiza admin/tournaments.html con el mensaje de error.
    Si tiene éxito redirige a redirect_to.

    Requerimientos: 4.1, 4.2, 4.3, 4.4
    """
    score_id = request.form.get("score_id", "").strip()
    arrow_val = request.form.get("arrow_val", "").strip()
    redirect_to = request.form.get("redirect_to", "") or url_for("admin.tournaments")

    result = correct_arrow_admin(score_id, arrow_val)

    if "error" in result:
        status_code = result.get("status_code", 400)
        return (
            render_template(
                "admin/tournaments.html",
                tournaments=list_tournaments(),
                error=result["error"],
                field=result.get("field"),
                form_data={},
            ),
            status_code,
        )

    return redirect(redirect_to)

# ---------------------------------------------------------------------------
# Configuración del club (branding / multi-tenant)
# ---------------------------------------------------------------------------

@admin_bp.route("/club", methods=["GET", "POST"])
@require_admin
def club_settings():
    """
    GET  — Renderiza el formulario de configuración del club.
    POST — Persiste los cambios de branding y redirige.
    """
    error = None
    field = None
    success = False

    settings = get_club_settings()

    if request.method == "POST":
        club_name    = request.form.get("club_name",    "").strip()
        hero_title   = request.form.get("hero_title",   "").strip()
        hero_subtitle= request.form.get("hero_subtitle","").strip()
        ticker_text  = request.form.get("ticker_text",  "").strip()
        color_from   = request.form.get("color_from",   "#166534").strip()
        color_to     = request.form.get("color_to",     "#16a34a").strip()

        result = save_club_settings(
            club_name, hero_title, hero_subtitle, ticker_text, color_from, color_to
        )

        if "error" in result:
            error = result["error"]
            field = result.get("field")
            # Mantener los valores que el usuario escribió
            settings = {
                "club_name":    club_name,
                "hero_title":   hero_title,
                "hero_subtitle":hero_subtitle,
                "ticker_text":  ticker_text,
                "color_from":   color_from,
                "color_to":     color_to,
            }
        else:
            success = True
            settings = get_club_settings()  # recargar desde DB

    return render_template(
        "admin/club_settings.html",
        settings=settings,
        error=error,
        field=field,
        success=success,
    )


# ---------------------------------------------------------------------------
# Gestor de Noticias y Alertas
# ---------------------------------------------------------------------------

@admin_bp.route("/news", methods=["GET", "POST"])
@require_admin
def news():
    """
    GET  — Lista todas las noticias.
    POST — Crea una nueva noticia.
    """
    error = None
    field = None
    form_data: dict = {}

    if request.method == "POST":
        title   = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        form_data = {"title": title, "content": content}

        result = create_news(title, content)
        if "error" in result:
            error = result["error"]
            field = result.get("field")
        else:
            return redirect(url_for("admin.news"))

    return render_template(
        "admin/news.html",
        news_items=list_news(),
        error=error,
        field=field,
        form_data=form_data,
    )


@admin_bp.route("/news/<news_id>/toggle", methods=["POST"])
@require_admin
def news_toggle(news_id: str):
    """POST — Activa o desactiva una noticia."""
    toggle_news(news_id)
    return redirect(url_for("admin.news"))


@admin_bp.route("/news/<news_id>/delete", methods=["POST"])
@require_admin
def news_delete(news_id: str):
    """POST — Elimina una noticia."""
    delete_news(news_id)
    return redirect(url_for("admin.news"))


# ---------------------------------------------------------------------------
# Edición de arquero
# ---------------------------------------------------------------------------

@admin_bp.route("/archers/<archer_id>/edit", methods=["GET", "POST"])
@require_admin
def edit_archer(archer_id: str):
    """
    GET  — Formulario de edición del arquero.
    POST — Persiste los cambios de nombre y PIN.
    """
    # Buscar arquero actual
    from archer.db import get_connection as _gc  # noqa: PLC0415
    try:
        conn = _gc()
        row = conn.execute(
            "SELECT id, name, pin FROM archers WHERE id = ?", (archer_id,)
        ).fetchone()
        if row is None:
            return redirect(url_for("admin.archers"))
        current = dict(row)
    except Exception:
        return redirect(url_for("admin.archers"))

    error = None
    field = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pin  = request.form.get("pin",  "").strip()
        result = update_archer(archer_id, name, pin)

        if "error" in result:
            error = result["error"]
            field = result.get("field")
            current = {"id": archer_id, "name": name, "pin": pin}
        else:
            return redirect(url_for("admin.archers"))

    return render_template(
        "admin/edit_archer.html",
        archer=current,
        error=error,
        field=field,
    )
