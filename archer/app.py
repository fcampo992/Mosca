"""
archer/app.py

Application factory.  Call create_app() to obtain a configured Flask instance.
Vercel uses the `app` variable at module level as the WSGI entrypoint.
"""

from __future__ import annotations

import logging
import os
import sys

from flask import Flask

from archer.config import Config

# Cargar variables de entorno desde .env (solo en desarrollo local)
try:
    from dotenv import load_dotenv  # noqa: PLC0415
    load_dotenv()
except ImportError:
    # python-dotenv no instalado — Vercel inyecta las vars directamente
    pass

# Configurar root logger — captura todos los loggers del proyecto en Vercel
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)


def create_app(config_object: object = Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config.from_object(config_object)

    if not app.config.get("SECRET_KEY") and not app.config.get("TESTING"):
        import warnings
        warnings.warn(
            "SESSION_SECRET not set — using insecure default. Set it in Vercel Environment Variables.",
            RuntimeWarning,
            stacklevel=2,
        )

    # ── Initialise database ───────────────────────────────────────────────────
    # Se hace en el primer request via before_request para evitar timeouts en import time
    _db_initialized = False

    @app.before_request
    def ensure_db():
        nonlocal _db_initialized
        if _db_initialized:
            return
        try:
            from archer.db import get_connection, init_db  # noqa: PLC0415
            logger.info("Inicializando base de datos...")
            conn = get_connection()
            logger.info("Conexión obtenida: %s", type(conn).__name__)
            init_db(conn)
            logger.info("Base de datos inicializada correctamente.")
            _db_initialized = True
        except Exception as exc:
            import traceback
            logger.error("Error inicializando DB: %s\n%s", exc, traceback.format_exc())
            # NO marcar como inicializado si falló — reintentar en el próximo request

    # ── Context processors ────────────────────────────────────────────────────
    @app.context_processor
    def inject_club_settings():
        """Inyecta club_settings() en todos los templates como función callable."""
        try:
            from archer.modules.club import get_club_settings  # noqa: PLC0415
            return {"club_settings": get_club_settings}
        except Exception:
            def _fallback():
                return {
                    "club_name": "KiroArchery",
                    "hero_title": "Tu torneo de arquería, en tiempo real",
                    "hero_subtitle": "",
                    "ticker_text": "🏹 Bienvenido",
                    "color_from": "#166534",
                    "color_to": "#16a34a",
                }
            return {"club_settings": _fallback}

    # ── Register blueprints ───────────────────────────────────────────────────
    try:
        from archer.routes.admin_routes import admin_bp  # noqa: PLC0415
        app.register_blueprint(admin_bp)
    except ImportError:
        logger.debug("admin_routes blueprint not available yet.")

    try:
        from archer.routes.archer_routes import archer_bp  # noqa: PLC0415
        app.register_blueprint(archer_bp)
    except ImportError:
        logger.debug("archer_routes blueprint not available yet.")

    try:
        from archer.routes.leaderboard_routes import leaderboard_bp  # noqa: PLC0415
        app.register_blueprint(leaderboard_bp)
    except ImportError:
        logger.debug("leaderboard_routes blueprint not available yet.")

    try:
        from archer.routes.stats_routes import stats_bp  # noqa: PLC0415
        app.register_blueprint(stats_bp)
    except ImportError:
        logger.debug("stats_routes blueprint not available yet.")

    try:
        from archer.routes.team_routes import team_admin_bp, team_archer_bp  # noqa: PLC0415
        app.register_blueprint(team_admin_bp)
        app.register_blueprint(team_archer_bp)
    except ImportError:
        logger.debug("team_routes blueprint not available yet.")

    # ── Google OAuth (authlib) ────────────────────────────────────────────────
    google_client_id     = os.environ.get("GOOGLE_CLIENT_ID")
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if google_client_id and google_client_secret:
        try:
            from authlib.integrations.flask_client import OAuth  # noqa: PLC0415
            oauth = OAuth(app)
            oauth.register(
                name="google",
                client_id=google_client_id,
                client_secret=google_client_secret,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )
            app.extensions["oauth"] = oauth
            logger.info("Google OAuth configurado correctamente.")
        except Exception as exc:
            logger.warning("No se pudo configurar Google OAuth: %s", exc)
    else:
        logger.info("GOOGLE_CLIENT_ID/SECRET no configurados — Google OAuth deshabilitado.")

    # ── Home route ───────────────────────────────────────────────────────────
    @app.route("/")
    def home():
        """Redirige según estado de sesión: dashboard si logueado, login si no."""
        from flask import redirect, url_for, session  # noqa: PLC0415
        from archer.modules.archer import is_session_valid  # noqa: PLC0415

        archer_id   = session.get("archer_id")
        last_active = session.get("last_active", "")

        if archer_id and is_session_valid(last_active):
            return redirect(url_for("archer.dashboard"))
        return redirect(url_for("archer.login"))

    # ── Health / debug endpoint ───────────────────────────────────────────────
    @app.route("/health")
    def health():
        from flask import jsonify  # noqa: PLC0415
        import os
        info = {
            "status": "ok",
            "turso_url_set": bool(os.environ.get("TURSO_DATABASE_URL")),
            "turso_token_set": bool(os.environ.get("TURSO_AUTH_TOKEN")),
            "cloudinary_set": bool(os.environ.get("CLOUDINARY_URL")),
        }
        try:
            from archer.db import get_connection  # noqa: PLC0415
            conn = get_connection()
            info["conn_type"] = type(conn).__name__
            info["conn_module"] = type(conn).__module__
            # Usar una query que sólo funciona en Turso/libSQL (no en sqlite_master vacío)
            cursor = conn.execute("SELECT 1 as ping")
            info["ping"] = cursor.fetchone()[0]
            cursor2 = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            info["tables"] = [r[0] for r in cursor2.fetchall()]
            info["db_type"] = "turso" if os.environ.get("TURSO_DATABASE_URL") else "sqlite"
        except Exception as e:
            info["db_error"] = str(e)
        return jsonify(info)
    from flask import jsonify  # noqa: PLC0415

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Recurso no encontrado."}), 404

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify({"error": "Datos de entrada no válidos.", "field": None}), 422

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({"error": "Demasiadas solicitudes. Intente más tarde."}), 429

    @app.errorhandler(503)
    def service_unavailable(e):
        return jsonify({"error": "Servicio no disponible temporalmente."}), 503

    return app


# ── Vercel WSGI entrypoint ────────────────────────────────────────────────────
# Vercel looks for a module-level `app` variable.
app = create_app()
