"""
archer/routes/archer_routes.py

Blueprint /archer — Autenticación PIN y carga de puntuaciones del arquero.

Rutas:
    GET  /archer/login    — formulario de PIN
    POST /archer/login    — autenticar PIN
    POST /archer/logout   — cerrar sesión
    GET  /archer/score    — vista del teclado táctil (requiere sesión activa)
    POST /archer/score    — guardar flecha (requiere sesión activa)

Requerimientos: 4.1–4.7, 5.1–5.7
"""

from __future__ import annotations

import functools
import os
import uuid as _uuid
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from archer.modules.archer import (
    ARROWS_PER_END,
    ENDS_PER_ROUND,
    authenticate_pin,
    correct_arrow_archer,
    get_accumulated_points,
    get_active_tournament,
    get_end_arrow_count,
    get_end_summary,
    is_session_valid,
    save_arrow,
)
from archer.modules.stats import archer_kpis, archer_history, archer_trend
from archer.modules.profile import (
    get_profile, save_profile, upload_banner,
    list_setups, get_setup, create_setup, update_setup, delete_setup,
)

archer_bp = Blueprint("archer", __name__, url_prefix="/archer")

# Extensiones permitidas para fotos de perfil
_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB


def _allowed_photo(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in _ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Session decorator (Req 4.4)
# ---------------------------------------------------------------------------

def require_session(view):
    """Decorador que verifica que existe una sesión activa válida (≤ 30 min).

    Si la sesión no existe o expiró, limpia la sesión y redirige a /archer/login.
    Si es válida, actualiza last_active antes de continuar.
    """
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        archer_id = session.get("archer_id")
        last_active = session.get("last_active", "")

        if not archer_id or not is_session_valid(last_active):
            session.clear()
            return redirect(url_for("archer.login"))

        # Actualizar last_active en cada request autenticado (Req 4.4)
        session["last_active"] = datetime.now().isoformat()
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Login / Logout (Req 4.1, 4.2, 4.5, 4.6, 4.7)
# ---------------------------------------------------------------------------

@archer_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    GET  — Renderiza el formulario de ingreso de PIN.
    POST — Autentica el PIN. Redirige a /archer/score si exitoso,
           re-renderiza con error si falla.

    Requerimientos: 4.1, 4.2, 4.6, 4.7
    """
    # Si ya tiene sesión válida, redirigir al dashboard
    if session.get("archer_id") and is_session_valid(session.get("last_active", "")):
        return redirect(url_for("archer.dashboard"))

    if request.method == "GET":
        return render_template("archer/login.html", error=None, field=None, locked=False)

    # POST — intentar autenticación
    pin = request.form.get("pin", "").strip()
    result = authenticate_pin(pin)

    if "error" not in result:
        archer_id   = result["archer_id"]
        archer_name = result["name"]

        # Calcular el estado actual del arquero en el torneo activo
        round_number = 1
        end_number   = 1
        tournament_done = False

        try:
            tournament = get_active_tournament(archer_id)
            if tournament:
                arrows_per_end = tournament.get("arrows_per_end", 6)
                ends_per_round = tournament.get("rounds", 10)
                rounds_count   = tournament.get("rounds_count", 1)

                # Contar cuántas flechas tiene registradas
                from archer.db import get_connection as _gc  # noqa: PLC0415
                conn = _gc()

                # Obtener la última flecha registrada para saber en qué ronda/tanda está
                last_row = conn.execute(
                    """SELECT round_number, end_number, COUNT(*) as cnt
                       FROM scores
                       WHERE archer_id = ? AND tournament_id = ?
                       GROUP BY round_number, end_number
                       ORDER BY round_number DESC, end_number DESC
                       LIMIT 1""",
                    (archer_id, tournament["id"]),
                ).fetchone()

                if last_row:
                    last_round = last_row["round_number"]
                    last_end   = last_row["end_number"]
                    last_cnt   = last_row["cnt"]

                    if last_cnt >= arrows_per_end:
                        # La última tanda está completa — avanzar
                        if last_end >= ends_per_round:
                            if last_round >= rounds_count:
                                tournament_done = True
                                round_number = last_round
                                end_number   = last_end
                            else:
                                round_number = last_round + 1
                                end_number   = 1
                        else:
                            round_number = last_round
                            end_number   = last_end + 1
                    else:
                        # La última tanda está incompleta — continuar ahí
                        round_number = last_round
                        end_number   = last_end
        except Exception:
            pass

        session["archer_id"]       = archer_id
        session["archer_name"]     = archer_name
        session["last_active"]     = datetime.now().isoformat()
        session["round_number"]    = round_number
        session["end_number"]      = end_number
        session["tournament_done"] = tournament_done
        session.pop("photo_url", None)  # forzar recarga de foto
        return redirect(url_for("archer.dashboard"))

    # Determinar código HTTP apropiado
    locked = result.get("blocked", False)
    if locked:
        status_code = 429
    elif result.get("field") == "pin":
        status_code = 400
    else:
        status_code = 401

    return render_template(
        "archer/login.html",
        error=result["error"],
        field=result.get("field"),
        locked=locked,
    ), status_code


@archer_bp.route("/logout", methods=["POST"])
def logout():
    """
    POST — Invalida la sesión activa y redirige al login.

    Requerimientos: 4.5
    """
    session.clear()
    return redirect(url_for("archer.login"))


# ---------------------------------------------------------------------------
# Dashboard personal del arquero
# ---------------------------------------------------------------------------

@archer_bp.route("/dashboard", methods=["GET"])
@require_session
def dashboard():
    """
    GET — Dashboard de rendimiento personal.
    Muestra KPIs históricos, estado del torneo activo, historial y gráfico.
    """
    archer_id   = session["archer_id"]
    archer_name = session.get("archer_name", "")
    photo_url   = session.get("photo_url")

    # Cargar foto si no está en sesión
    if not photo_url:
        try:
            from archer.db import get_connection  # noqa: PLC0415
            conn = get_connection()
            row = conn.execute(
                "SELECT photo_url FROM archers WHERE id = ?", (archer_id,)
            ).fetchone()
            if row and row["photo_url"]:
                photo_url = row["photo_url"]
                session["photo_url"] = photo_url
        except Exception:
            pass

    tournament  = get_active_tournament(archer_id)
    kpis        = archer_kpis(archer_id)
    history     = archer_history(archer_id)
    trend       = archer_trend(archer_id)

    return render_template(
        "archer/dashboard.html",
        archer_name=archer_name,
        photo_url=photo_url,
        tournament=tournament,
        kpis=kpis,
        history=history,
        trend=trend,
    )


# ---------------------------------------------------------------------------
# Score entry (Req 5.1–5.7)
# ---------------------------------------------------------------------------

def _render_score(error=None):
    """Helper interno: construye los datos necesarios para renderizar score.html."""
    archer_id    = session["archer_id"]
    round_number = session.get("round_number", 1)
    end_number   = session.get("end_number", 1)
    archer_name  = session.get("archer_name", "")
    photo_url    = session.get("photo_url")
    tournament_done = session.get("tournament_done", False)

    if not photo_url:
        try:
            from archer.db import get_connection  # noqa: PLC0415
            conn = get_connection()
            row = conn.execute(
                "SELECT photo_url FROM archers WHERE id = ?", (archer_id,)
            ).fetchone()
            if row and row["photo_url"]:
                photo_url = row["photo_url"]
                session["photo_url"] = photo_url
        except Exception:
            pass

    tournament = get_active_tournament(archer_id)

    if tournament is None:
        return render_template(
            "archer/score.html",
            tournament=None,
            no_tournament=True,
            tournament_done=False,
            accumulated=0,
            end_summary={"arrows": [], "subtotal": 0},
            round_number=round_number,
            end_number=end_number,
            archer_name=archer_name,
            photo_url=photo_url,
            arrows_per_end=ARROWS_PER_END,
            ends_per_round=ENDS_PER_ROUND,
            error=error,
        )

    accumulated    = get_accumulated_points(archer_id, tournament["id"])
    end_summary    = get_end_summary(archer_id, tournament["id"], round_number, end_number)
    arrows_per_end = tournament.get("arrows_per_end", ARROWS_PER_END)
    ends_per_round = tournament.get("rounds", ENDS_PER_ROUND)
    rounds_count   = tournament.get("rounds_count", 1)

    # Verificar si el torneo está completado (sin depender solo de la sesión)
    if not tournament_done:
        tournament_done = (
            round_number > rounds_count or
            (round_number == rounds_count and
             end_number > ends_per_round)
        )

    return render_template(
        "archer/score.html",
        tournament=tournament,
        no_tournament=False,
        tournament_done=tournament_done,
        accumulated=accumulated,
        end_summary=end_summary,
        round_number=round_number,
        end_number=end_number,
        archer_name=archer_name,
        photo_url=photo_url,
        arrows_per_end=arrows_per_end,
        ends_per_round=ends_per_round,
        rounds_count=rounds_count,
        error=error,
    )


@archer_bp.route("/score", methods=["GET"])
@require_session
def score():
    """
    GET — Vista del teclado táctil de carga de flechas.

    Requerimientos: 5.1, 5.6, 5.7
    """
    return _render_score()


@archer_bp.route("/score", methods=["POST"])
@require_session
def score_post():
    """
    POST — Guarda una flecha. Si hay error re-renderiza sin avanzar el estado.
    Si tiene éxito redirige (PRG) al GET de /archer/score.

    Requerimientos: 5.2, 5.3, 5.4, 5.5
    """
    archer_id = session["archer_id"]
    round_number = session.get("round_number", 1)
    end_number = session.get("end_number", 1)

    # Obtener torneo activo
    tournament = get_active_tournament(archer_id)
    if tournament is None:
        return _render_score(error="No hay torneos activos asignados."), 403

    arrow_val = request.form.get("arrow_val", "").strip()

    result = save_arrow(
        archer_id=archer_id,
        tournament_id=tournament["id"],
        round_number=round_number,
        end_number=end_number,
        arrow_val=arrow_val,
    )

    if "error" in result:
        # Req 5.3 — fallo en persistencia: no avanzar, mostrar error
        return _render_score(error=result["error"]), 500

    # Éxito — comprobar si se completó la tanda y avanzar sesión (Req 2.1, 2.2)
    # Leer configuración del torneo en lugar de usar constantes globales (Req 2.4)
    arrows_per_end = tournament.get("arrows_per_end", ARROWS_PER_END)
    ends_per_round = tournament.get("rounds", ENDS_PER_ROUND)
    rounds_count   = tournament.get("rounds_count", 1)

    arrow_count = get_end_arrow_count(
        archer_id, tournament["id"], round_number, end_number
    )
    if arrow_count >= arrows_per_end:
        is_last_end   = (end_number >= ends_per_round)
        is_last_round = (round_number >= rounds_count)

        if is_last_end and is_last_round:
            # Torneo completo — marcar en sesión, no avanzar más
            session["tournament_done"] = True
        elif is_last_end:
            # Avanzar a la siguiente ronda
            session["end_number"]   = 1
            session["round_number"] = round_number + 1
        else:
            session["end_number"] = end_number + 1

    session["last_active"] = datetime.now().isoformat()
    return redirect(url_for("archer.score"))


@archer_bp.route("/score/correct", methods=["POST"])
@require_session
def correct_arrow():
    """
    POST — Corrige el valor de una flecha en la tanda activa del arquero.

    Requerimientos: 3.1, 3.2, 3.3, 3.4
    """
    archer_id = session["archer_id"]
    round_number = session.get("round_number", 1)
    end_number = session.get("end_number", 1)

    score_id = request.form.get("score_id", "").strip()
    arrow_val = request.form.get("arrow_val", "").strip()

    # Obtener torneo activo (Req 3.4)
    tournament = get_active_tournament(archer_id)
    if tournament is None:
        return _render_score(error="No hay torneos activos asignados."), 403

    tournament_id = tournament["id"]

    result = correct_arrow_archer(
        score_id=score_id,
        arrow_val=arrow_val,
        archer_id=archer_id,
        tournament_id=tournament_id,
        current_round=round_number,
        current_end=end_number,
    )

    if "error" in result:
        status_code = result.get("status_code", 400)
        return _render_score(error=result["error"]), status_code

    # Éxito — actualizar last_active y redirigir (PRG)
    session["last_active"] = datetime.now().isoformat()
    return redirect(url_for("archer.score"))


# ---------------------------------------------------------------------------
# Foto de perfil del arquero
# ---------------------------------------------------------------------------

@archer_bp.route("/profile/photo", methods=["POST"])
@require_session
def upload_photo():
    """
    POST — Sube o reemplaza la foto de perfil del arquero.
    Usa Cloudinary si CLOUDINARY_URL está configurada, sino guarda en disco.
    """
    archer_id = session["archer_id"]

    if "photo" not in request.files:
        return _render_score(error="No se recibió ningún archivo."), 400

    photo = request.files["photo"]

    if photo.filename == "":
        return _render_score(error="Seleccioná una imagen antes de subir."), 400

    if not _allowed_photo(photo.filename):
        return _render_score(error="Formato no permitido. Usá JPG, PNG, WEBP o GIF."), 400

    data = photo.read()
    if len(data) > _MAX_PHOTO_BYTES:
        return _render_score(error="La imagen supera el límite de 5 MB."), 400

    photo_url = None

    # ── Intentar Cloudinary primero ──
    cloudinary_url = os.environ.get("CLOUDINARY_URL")
    if cloudinary_url:
        try:
            import cloudinary                          # type: ignore
            import cloudinary.uploader                 # type: ignore
            import io
            # Configurar explícitamente desde la URL de entorno
            cloudinary.config(cloudinary_url=cloudinary_url)
            result = cloudinary.uploader.upload(
                io.BytesIO(data),
                public_id=f"archer_photos/{archer_id}",
                overwrite=True,
                resource_type="image",
                transformation=[{"width": 400, "height": 400, "crop": "fill", "gravity": "face"}],
            )
            photo_url = result.get("secure_url")
        except Exception as exc:
            return _render_score(error=f"Error al subir a Cloudinary: {exc}"), 500
    else:
        # ── Fallback: disco local ──
        ext = photo.filename.rsplit(".", 1)[1].lower()
        filename = f"{archer_id}.{ext}"
        photos_dir = os.path.join(current_app.root_path, "static", "photos")
        os.makedirs(photos_dir, exist_ok=True)
        filepath = os.path.join(photos_dir, filename)
        with open(filepath, "wb") as f:
            f.write(data)
        photo_url = f"/static/photos/{filename}"

    # ── Persistir URL en DB ──
    try:
        from archer.db import get_connection  # noqa: PLC0415
        conn = get_connection()
        conn.execute(
            "UPDATE archers SET photo_url = ? WHERE id = ?",
            (photo_url, archer_id),
        )
        try:
            conn.commit()
        except Exception:
            pass
        session["photo_url"] = photo_url
    except Exception as exc:
        return _render_score(error=f"Error al guardar la foto: {exc}"), 500

    return redirect(url_for("archer.score"))


# ---------------------------------------------------------------------------
# Perfil del arquero
# ---------------------------------------------------------------------------

@archer_bp.route("/profile", methods=["GET", "POST"])
@require_session
def profile():
    """
    GET  — Muestra el perfil extendido del arquero (datos personales + banner).
    POST — Persiste los cambios del formulario.
    """
    archer_id = session["archer_id"]
    error = None
    field = None
    success = False

    if request.method == "POST":
        result = save_profile(
            archer_id=archer_id,
            name=request.form.get("name", "").strip(),
            nickname=request.form.get("nickname", "").strip(),
            club=request.form.get("club", "").strip(),
            dominant_hand=request.form.get("dominant_hand", "Diestro").strip(),
            bow_category=request.form.get("bow_category", "").strip(),
            season_goal=request.form.get("season_goal", "").strip(),
        )
        if "error" in result:
            error = result["error"]
            field = result.get("field")
        else:
            # Actualizar nombre en sesión
            session["archer_name"] = request.form.get("name", session.get("archer_name", ""))
            success = True

    profile_data = get_profile(archer_id)
    setups = list_setups(archer_id)

    return render_template(
        "archer/profile.html",
        profile=profile_data,
        setups=setups,
        error=error,
        field=field,
        success=success,
    )


@archer_bp.route("/profile/banner", methods=["POST"])
@require_session
def upload_banner_route():
    """POST — Sube la imagen de banner a Cloudinary."""
    archer_id = session["archer_id"]

    if "banner" not in request.files:
        return redirect(url_for("archer.profile"))

    banner = request.files["banner"]
    if banner.filename == "":
        return redirect(url_for("archer.profile"))

    if not _allowed_photo(banner.filename):
        return render_template(
            "archer/profile.html",
            profile=get_profile(archer_id),
            setups=list_setups(archer_id),
            error="Formato no permitido. Usá JPG, PNG o WEBP.",
            field="banner",
            success=False,
        ), 400

    data = banner.read()
    if len(data) > _MAX_PHOTO_BYTES:
        return render_template(
            "archer/profile.html",
            profile=get_profile(archer_id),
            setups=list_setups(archer_id),
            error="La imagen supera el límite de 5 MB.",
            field="banner",
            success=False,
        ), 400

    result = upload_banner(archer_id, data, banner.filename)
    if "error" in result:
        return render_template(
            "archer/profile.html",
            profile=get_profile(archer_id),
            setups=list_setups(archer_id),
            error=result["error"],
            field="banner",
            success=False,
        ), 500

    return redirect(url_for("archer.profile"))


# ---------------------------------------------------------------------------
# Equipo del arquero (bow setups)
# ---------------------------------------------------------------------------

@archer_bp.route("/equipment", methods=["GET"])
@require_session
def equipment():
    """GET — Lista todos los setups de equipo del arquero."""
    archer_id = session["archer_id"]
    setups = list_setups(archer_id)
    return render_template(
        "archer/equipment.html",
        setups=setups,
        error=None,
        field=None,
        form_data={},
        edit_setup=None,
    )


@archer_bp.route("/equipment/new", methods=["POST"])
@require_session
def equipment_new():
    """POST — Crea un nuevo setup de equipo."""
    archer_id = session["archer_id"]
    form = request.form

    # Parsear sight_marks desde el formulario (JSON enviado como campo oculto)
    import json as _json
    try:
        sight_marks = _json.loads(form.get("sight_marks_json", "[]"))
    except Exception:
        sight_marks = []

    result = create_setup(
        archer_id=archer_id,
        name=form.get("name", ""),
        bow_type=form.get("bow_type", ""),
        draw_weight=form.get("draw_weight", ""),
        draw_length=form.get("draw_length", ""),
        string_material=form.get("string_material", ""),
        arrow_model=form.get("arrow_model", ""),
        arrow_spine=form.get("arrow_spine", ""),
        arrow_length=form.get("arrow_length", ""),
        point_weight=form.get("point_weight", ""),
        vanes=form.get("vanes", ""),
        nock=form.get("nock", ""),
        sight_marks=sight_marks,
    )

    if "error" in result:
        return render_template(
            "archer/equipment.html",
            setups=list_setups(archer_id),
            error=result["error"],
            field=result.get("field"),
            form_data=dict(form),
            edit_setup=None,
        ), 400

    return redirect(url_for("archer.equipment"))


@archer_bp.route("/equipment/<setup_id>/edit", methods=["GET", "POST"])
@require_session
def equipment_edit(setup_id: str):
    """
    GET  — Carga el formulario de edición del setup.
    POST — Persiste los cambios.
    """
    archer_id = session["archer_id"]
    setup = get_setup(setup_id, archer_id)
    if setup is None:
        return redirect(url_for("archer.equipment"))

    if request.method == "GET":
        return render_template(
            "archer/equipment.html",
            setups=list_setups(archer_id),
            error=None,
            field=None,
            form_data={},
            edit_setup=setup,
        )

    # POST
    import json as _json
    try:
        sight_marks = _json.loads(request.form.get("sight_marks_json", "[]"))
    except Exception:
        sight_marks = []

    result = update_setup(
        setup_id=setup_id,
        archer_id=archer_id,
        name=request.form.get("name", ""),
        bow_type=request.form.get("bow_type", ""),
        draw_weight=request.form.get("draw_weight", ""),
        draw_length=request.form.get("draw_length", ""),
        string_material=request.form.get("string_material", ""),
        arrow_model=request.form.get("arrow_model", ""),
        arrow_spine=request.form.get("arrow_spine", ""),
        arrow_length=request.form.get("arrow_length", ""),
        point_weight=request.form.get("point_weight", ""),
        vanes=request.form.get("vanes", ""),
        nock=request.form.get("nock", ""),
        sight_marks=sight_marks,
    )

    if "error" in result:
        return render_template(
            "archer/equipment.html",
            setups=list_setups(archer_id),
            error=result["error"],
            field=result.get("field"),
            form_data=dict(request.form),
            edit_setup=setup,
        ), 400

    return redirect(url_for("archer.equipment"))


@archer_bp.route("/equipment/<setup_id>/delete", methods=["POST"])
@require_session
def equipment_delete(setup_id: str):
    """POST — Elimina (soft-delete) un setup."""
    archer_id = session["archer_id"]
    delete_setup(setup_id, archer_id)
    return redirect(url_for("archer.equipment"))
