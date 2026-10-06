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
    export_archers_csv,
    get_archer_activity,
    get_archer_detail,
    get_tournament,
    list_archers,
    list_categories,
    list_enrolled_archers,
    list_tournaments,
    update_archer,
    unenroll_archer,
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
        return redirect(url_for("admin.panel"))

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
# Panel principal — /admin/panel
# ---------------------------------------------------------------------------

@admin_bp.route("/")
@require_admin
def index():
    """Redirige /admin → /admin/panel."""
    return redirect(url_for("admin.panel"))


@admin_bp.route("/panel")
@require_admin
def panel():
    """GET — Dashboard del panel de administración."""
    from archer.db import get_connection  # noqa: PLC0415

    conn = get_connection()

    # KPIs
    total_archers = conn.execute(
        "SELECT COUNT(*) AS c FROM archers WHERE auth_provider != 'pin' OR email IS NOT NULL"
    ).fetchone()["c"]

    pending_archers = conn.execute(
        "SELECT COUNT(*) AS c FROM archers WHERE status = 'pending'"
    ).fetchone()["c"]

    active_tournaments = conn.execute(
        "SELECT COUNT(*) AS c FROM tournaments WHERE status = 'active'"
    ).fetchone()["c"]

    finished_tournaments = conn.execute(
        "SELECT COUNT(*) AS c FROM tournaments WHERE status = 'finished'"
    ).fetchone()["c"]

    # Arqueros pendientes (lista para la card de alerta)
    pending_list = conn.execute(
        """
        SELECT id, name, email, auth_provider, created_at
        FROM archers WHERE status = 'pending'
        ORDER BY created_at DESC LIMIT 10
        """
    ).fetchall()

    return render_template(
        "admin/panel.html",
        kpis={
            "total_archers":      total_archers,
            "pending_archers":    pending_archers,
            "active_tournaments": active_tournaments,
            "finished_tournaments": finished_tournaments,
        },
        pending_list=[dict(r) for r in pending_list],
    )


@admin_bp.route("/panel/archer/<archer_id>/approve", methods=["POST"])
@require_admin
def approve_archer(archer_id: str):
    """POST — Aprueba un arquero pendiente."""
    from archer.db import get_connection  # noqa: PLC0415
    conn = get_connection()
    conn.execute(
        "UPDATE archers SET status = 'active' WHERE id = ?", (archer_id,)
    )
    try:
        conn.commit()
    except Exception:
        pass
    logger.info("Admin aprobó archer_id=%s", archer_id)
    return redirect(url_for("admin.panel"))


@admin_bp.route("/panel/archer/<archer_id>/reject", methods=["POST"])
@require_admin
def reject_archer(archer_id: str):
    """POST — Rechaza (suspende) un arquero pendiente."""
    from archer.db import get_connection  # noqa: PLC0415
    conn = get_connection()
    conn.execute(
        "UPDATE archers SET status = 'suspended' WHERE id = ?", (archer_id,)
    )
    try:
        conn.commit()
    except Exception:
        pass
    logger.info("Admin rechazó archer_id=%s", archer_id)
    return redirect(url_for("admin.panel"))


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
        target_type  = request.form.get("target_type", "wa10").strip()
        form_data = {"name": name, "date": date, "rounds": rounds, "arrows_per_end": arrows_per_end, "rounds_count": rounds_count}

        result = create_tournament(name, date, rounds=rounds, arrows_per_end=arrows_per_end, rounds_count=rounds_count, target_type=target_type)

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
    all_archers = list_archers()   # todos los arqueros para el formulario de inscripción
    return render_template(
        "admin/tournament_detail.html",
        tournament=tournament,
        categories=categories_list,
        archers=archers_list,
        all_archers=all_archers,
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
    POST — Crea un nuevo arquero PIN; si hay error re-renderiza con mensaje.
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

        return redirect(url_for("admin.archers"))

    # GET — pasar filtro activo desde query param
    status_filter = request.args.get("status", "all")
    return render_template(
        "admin/archers.html",
        archers=list_archers(),
        tournaments=list_tournaments(),
        error=error,
        field=field,
        form_data=form_data,
        enroll_error=None,
        status_filter=status_filter,
    )


@admin_bp.route("/archers/export.csv", methods=["GET"])
@require_admin
def archers_export_csv():
    """GET — Descarga CSV con todos los arqueros y sus stats."""
    from flask import Response  # noqa: PLC0415
    csv_content = export_archers_csv()
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=arqueros.csv"},
    )


@admin_bp.route("/archers/<archer_id>", methods=["GET"])
@require_admin
def archer_profile(archer_id: str):
    """GET — Ficha detallada del arquero: stats, historial, actividad."""
    archer = get_archer_detail(archer_id)
    if archer is None:
        return redirect(url_for("admin.archers"))
    activity = get_archer_activity(archer_id)
    return render_template(
        "admin/archer_profile.html",
        archer=archer,
        activity=activity,
    )


@admin_bp.route("/archers/<archer_id>/approve", methods=["POST"])
@require_admin
def approve_archer_inline(archer_id: str):
    """POST — Aprueba un arquero pendiente desde la lista de arqueros."""
    from archer.db import get_connection as _gc  # noqa: PLC0415
    conn = _gc()
    conn.execute("UPDATE archers SET status = 'active' WHERE id = ?", (archer_id,))
    try:
        conn.commit()
    except Exception:
        pass
    logger.info("Admin aprobó archer_id=%s", archer_id)
    redirect_to = request.form.get("redirect_to", "") or url_for("admin.archers")
    return redirect(redirect_to)


@admin_bp.route("/archers/<archer_id>/reject", methods=["POST"])
@require_admin
def reject_archer_inline(archer_id: str):
    """POST — Suspende un arquero pendiente desde la lista de arqueros."""
    from archer.db import get_connection as _gc  # noqa: PLC0415
    conn = _gc()
    conn.execute("UPDATE archers SET status = 'suspended' WHERE id = ?", (archer_id,))
    try:
        conn.commit()
    except Exception:
        pass
    logger.info("Admin rechazó archer_id=%s", archer_id)
    redirect_to = request.form.get("redirect_to", "") or url_for("admin.archers")
    return redirect(redirect_to)


@admin_bp.route("/archers/<archer_id>/status", methods=["POST"])
@require_admin
def archer_set_status(archer_id: str):
    """POST — Cambia el status de un arquero (active / suspended). Desde el perfil."""
    from archer.db import get_connection as _gc  # noqa: PLC0415
    new_status = request.form.get("status", "").strip()
    if new_status not in ("active", "suspended", "pending"):
        return redirect(url_for("admin.archer_profile", archer_id=archer_id))
    conn = _gc()
    conn.execute("UPDATE archers SET status = ? WHERE id = ?", (new_status, archer_id))
    try:
        conn.commit()
    except Exception:
        pass
    return redirect(url_for("admin.archer_profile", archer_id=archer_id))


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
    redirect_to = request.form.get("redirect_to", "").strip() or url_for("admin.archers")

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

    return redirect(redirect_to)


@admin_bp.route("/tournaments/<tournament_id>/archers/<archer_id>/unenroll", methods=["POST"])
@require_admin
def unenroll(tournament_id: str, archer_id: str):
    """POST — Desinscribe un arquero de un torneo (elimina todas sus inscripciones en ese torneo)."""
    result = unenroll_archer(tournament_id, archer_id)
    if "error" in result:
        # Volver al detalle del torneo con mensaje de error
        tournament = get_tournament(tournament_id)
        archers = list_enrolled_archers(tournament_id)
        categories = list_categories(tournament_id)
        enrolled_ids = {a["archer_id"] for a in archers}
        all_archers = list_archers()
        return render_template(
            "admin/tournament_detail.html",
            tournament=tournament,
            archers=archers,
            categories=categories,
            enrolled_ids=enrolled_ids,
            all_archers=all_archers,
            unenroll_error=result["error"],
        ), 400
    return redirect(url_for("admin.tournament_detail", tournament_id=tournament_id))


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
        color_from   = request.form.get("color_from",   "#166534").strip()
        color_to     = request.form.get("color_to",     "#16a34a").strip()

        # ticker_text y ticker_enabled ya no se editan desde aquí — viven en Gestor de Noticias
        existing_ticker = settings.get("ticker_text", "")
        existing_ticker_enabled = int(settings.get("ticker_enabled", 1))

        result = save_club_settings(
            club_name, hero_title, hero_subtitle,
            ticker_text=existing_ticker,
            color_from=color_from,
            color_to=color_to,
            ticker_enabled=existing_ticker_enabled,
        )

        if "error" in result:
            error = result["error"]
            field = result.get("field")
            settings = {
                "club_name":    club_name,
                "hero_title":   hero_title,
                "hero_subtitle":hero_subtitle,
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


# ---------------------------------------------------------------------------
# Panel de Club — /admin/club/panel  (banners, noticias, recursos, config)
# La ruta legacy /admin/club sigue funcionando para branding básico.
# ---------------------------------------------------------------------------

from archer.modules.club_content import (  # noqa: E402
    create_banner, delete_banner, list_banners, move_banner, toggle_banner,
    create_news_item, delete_news_item, get_news_item,
    list_news as list_club_news, toggle_news_status, update_news_item,
    create_resource, create_resource_category, delete_resource,
    delete_resource_category, list_resource_categories, list_resources,
    toggle_resource,
)


@admin_bp.route("/club/panel", methods=["GET"])
@require_admin
def club_panel():
    """GET — Panel de gestión del club: Banners, Noticias, Recursos, Config."""
    tab = request.args.get("tab", "banners")
    return render_template(
        "admin/club_panel.html",
        tab=tab,
        banners=list_banners(),
        news_items=list_club_news(),
        resources=list_resources(),
        categories=list_resource_categories(),
        settings=get_club_settings(),
    )


# ── Banners ──────────────────────────────────────────────────────────────────

@admin_bp.route("/club/banners/new", methods=["POST"])
@require_admin
def club_banner_new():
    """POST — Sube un nuevo banner (imagen ya subida a Cloudinary)."""
    image_url  = request.form.get("image_url",  "").strip()
    title      = request.form.get("title",      "").strip()
    link_type  = request.form.get("link_type",  "none").strip()
    link_value = request.form.get("link_value", "").strip()

    result = create_banner(image_url, title=title, link_type=link_type, link_value=link_value)
    if "error" in result:
        # Volver al panel con error en tab banners
        return redirect(url_for("admin.club_panel", tab="banners", error=result["error"]))
    return redirect(url_for("admin.club_panel", tab="banners"))


@admin_bp.route("/club/banners/<banner_id>/delete", methods=["POST"])
@require_admin
def club_banner_delete(banner_id: str):
    """POST — Elimina un banner."""
    delete_banner(banner_id)
    return redirect(url_for("admin.club_panel", tab="banners"))


@admin_bp.route("/club/banners/<banner_id>/toggle", methods=["POST"])
@require_admin
def club_banner_toggle(banner_id: str):
    """POST — Activa/desactiva un banner."""
    toggle_banner(banner_id)
    return redirect(url_for("admin.club_panel", tab="banners"))


@admin_bp.route("/club/banners/<banner_id>/move/<direction>", methods=["POST"])
@require_admin
def club_banner_move(banner_id: str, direction: str):
    """POST — Mueve un banner arriba o abajo en el orden."""
    move_banner(banner_id, direction)
    return redirect(url_for("admin.club_panel", tab="banners"))


@admin_bp.route("/club/banners/upload", methods=["POST"])
@require_admin
def club_banner_upload():
    """POST — Sube imagen a Cloudinary y redirige al panel con la URL resultante."""
    import os as _os  # noqa: PLC0415
    import cloudinary.uploader as _cu  # noqa: PLC0415

    file = request.files.get("file")
    if not file or not file.filename:
        return redirect(url_for("admin.club_panel", tab="banners", error="No se recibió ningún archivo."))

    try:
        result = _cu.upload(file, folder="club_banners", resource_type="image")
        image_url = result.get("secure_url", "")
    except Exception as exc:
        logger.error("club_banner_upload: %s", exc)
        return redirect(url_for("admin.club_panel", tab="banners", error="Error al subir la imagen."))

    title      = request.form.get("title",      "").strip()
    link_type  = request.form.get("link_type",  "none").strip()
    link_value = request.form.get("link_value", "").strip()
    create_banner(image_url, title=title, link_type=link_type, link_value=link_value)
    return redirect(url_for("admin.club_panel", tab="banners"))


# ── Noticias ─────────────────────────────────────────────────────────────────

@admin_bp.route("/club/news/new", methods=["GET", "POST"])
@require_admin
def club_news_new():
    """GET — Formulario de creación. POST — Persiste la noticia."""
    if request.method == "POST":
        title       = request.form.get("title",       "").strip()
        excerpt     = request.form.get("excerpt",     "").strip()
        body_html   = request.form.get("body_html",   "").strip()
        cover_url   = request.form.get("cover_url",   "").strip()
        status      = request.form.get("status",      "draft").strip()
        published_at= request.form.get("published_at","").strip()

        result = create_news_item(
            title=title, excerpt=excerpt, body_html=body_html,
            cover_url=cover_url, status=status, published_at=published_at,
        )
        if "error" in result:
            return render_template(
                "admin/club_news_form.html",
                action="new", news=None,
                error=result["error"], field=result.get("field"),
                form_data=request.form,
            ), 400
        return redirect(url_for("admin.club_panel", tab="news"))

    return render_template("admin/club_news_form.html", action="new", news=None,
                           error=None, field=None, form_data={})


@admin_bp.route("/club/news/<news_id>/edit", methods=["GET", "POST"])
@require_admin
def club_news_edit(news_id: str):
    """GET — Formulario de edición. POST — Persiste cambios."""
    news = get_news_item(news_id)
    if not news:
        return redirect(url_for("admin.club_panel", tab="news"))

    if request.method == "POST":
        title       = request.form.get("title",       "").strip()
        excerpt     = request.form.get("excerpt",     "").strip()
        body_html   = request.form.get("body_html",   "").strip()
        cover_url   = request.form.get("cover_url",   "").strip()
        status      = request.form.get("status",      "draft").strip()
        published_at= request.form.get("published_at","").strip()

        result = update_news_item(
            news_id=news_id, title=title, excerpt=excerpt, body_html=body_html,
            cover_url=cover_url, status=status, published_at=published_at,
        )
        if "error" in result:
            return render_template(
                "admin/club_news_form.html",
                action="edit", news=news,
                error=result["error"], field=result.get("field"),
                form_data=request.form,
            ), 400
        return redirect(url_for("admin.club_panel", tab="news"))

    return render_template("admin/club_news_form.html", action="edit", news=news,
                           error=None, field=None, form_data=news)


@admin_bp.route("/club/news/<news_id>/delete", methods=["POST"])
@require_admin
def club_news_delete(news_id: str):
    """POST — Elimina una noticia."""
    delete_news_item(news_id)
    return redirect(url_for("admin.club_panel", tab="news"))


@admin_bp.route("/club/news/<news_id>/toggle", methods=["POST"])
@require_admin
def club_news_toggle(news_id: str):
    """POST — Publica o vuelve a borrador una noticia."""
    toggle_news_status(news_id)
    return redirect(url_for("admin.club_panel", tab="news"))


@admin_bp.route("/club/news/<news_id>/cover", methods=["POST"])
@require_admin
def club_news_cover_upload(news_id: str):
    """POST — Sube imagen de portada a Cloudinary y actualiza la noticia."""
    import os as _os  # noqa: PLC0415
    import cloudinary.uploader as _cu  # noqa: PLC0415

    file = request.files.get("file")
    if not file or not file.filename:
        return redirect(url_for("admin.club_news_edit", news_id=news_id))

    try:
        result = _cu.upload(file, folder="club_news_covers", resource_type="image")
        cover_url = result.get("secure_url", "")
    except Exception as exc:
        logger.error("club_news_cover_upload: %s", exc)
        return redirect(url_for("admin.club_news_edit", news_id=news_id))

    news = get_news_item(news_id)
    if news:
        update_news_item(
            news_id=news_id,
            title=news["title"],
            excerpt=news.get("excerpt", ""),
            body_html=news.get("body_html", ""),
            cover_url=cover_url,
            status=news.get("status", "draft"),
            published_at=news.get("published_at", ""),
        )
    return redirect(url_for("admin.club_news_edit", news_id=news_id))


# ── Categorías de recursos ────────────────────────────────────────────────────

@admin_bp.route("/club/categories/new", methods=["POST"])
@require_admin
def club_category_new():
    """POST — Crea una categoría de recursos."""
    name = request.form.get("name", "").strip()
    create_resource_category(name)
    return redirect(url_for("admin.club_panel", tab="resources"))


@admin_bp.route("/club/categories/<cat_id>/delete", methods=["POST"])
@require_admin
def club_category_delete(cat_id: str):
    """POST — Elimina una categoría (desvincula sus recursos)."""
    delete_resource_category(cat_id)
    return redirect(url_for("admin.club_panel", tab="resources"))


# ── Recursos ─────────────────────────────────────────────────────────────────

@admin_bp.route("/club/resources/new", methods=["POST"])
@require_admin
def club_resource_new():
    """POST — Crea un recurso (URL externa o link de Drive/Cloudinary)."""
    title       = request.form.get("title",       "").strip()
    file_url    = request.form.get("file_url",    "").strip()
    description = request.form.get("description", "").strip()
    category_id = request.form.get("category_id", "").strip()
    file_type   = request.form.get("file_type",   "link").strip()

    result = create_resource(
        title=title, file_url=file_url, description=description,
        category_id=category_id, file_type=file_type,
    )
    if "error" in result:
        return redirect(url_for("admin.club_panel", tab="resources", error=result["error"]))
    return redirect(url_for("admin.club_panel", tab="resources"))


@admin_bp.route("/club/resources/<res_id>/delete", methods=["POST"])
@require_admin
def club_resource_delete(res_id: str):
    """POST — Elimina un recurso."""
    delete_resource(res_id)
    return redirect(url_for("admin.club_panel", tab="resources"))


@admin_bp.route("/club/resources/<res_id>/toggle", methods=["POST"])
@require_admin
def club_resource_toggle(res_id: str):
    """POST — Activa/oculta un recurso."""
    toggle_resource(res_id)
    return redirect(url_for("admin.club_panel", tab="resources"))


# ── Config del carrusel (banner_interval) ────────────────────────────────────

@admin_bp.route("/club/config", methods=["POST"])
@require_admin
def club_config_save():
    """POST — Guarda configuración del carrusel (intervalo) y branding básico."""
    from archer.db import get_connection as _gc  # noqa: PLC0415
    interval = request.form.get("banner_interval", "5").strip()
    try:
        interval = max(2, min(30, int(interval)))
    except ValueError:
        interval = 5

    conn = _gc()
    conn.execute(
        "UPDATE club_settings SET banner_interval = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 'default'",
        (interval,),
    )
    try:
        conn.commit()
    except Exception:
        pass

    # También guardar branding si viene en el mismo POST
    club_name     = request.form.get("club_name",     "").strip()
    hero_title    = request.form.get("hero_title",    "").strip()
    hero_subtitle = request.form.get("hero_subtitle", "").strip()
    color_from    = request.form.get("color_from",    "").strip()
    color_to      = request.form.get("color_to",      "").strip()

    if club_name and hero_title and color_from and color_to:
        settings = get_club_settings()
        save_club_settings(
            club_name, hero_title, hero_subtitle,
            ticker_text=settings.get("ticker_text", ""),
            color_from=color_from, color_to=color_to,
            ticker_enabled=int(settings.get("ticker_enabled", 1)),
        )

    return redirect(url_for("admin.club_panel", tab="config", success="1"))
