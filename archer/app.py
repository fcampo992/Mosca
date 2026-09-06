"""
archer/app.py

Application factory.  Call create_app() to obtain a configured Flask instance.
Vercel uses the `app` variable at module level as the WSGI entrypoint.
"""

from __future__ import annotations

import logging

from flask import Flask

from archer.config import Config

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
            conn = get_connection()
            init_db(conn)
            _db_initialized = True
        except Exception as exc:
            logger.error("Error inicializando DB: %s", exc)

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

    # ── Home route ───────────────────────────────────────────────────────────
    @app.route("/")
    def home():
        from flask import render_template  # noqa: PLC0415
        from archer.modules.club import get_club_settings  # noqa: PLC0415
        from archer.modules.news import get_active_news  # noqa: PLC0415
        try:
            from archer.db import get_connection  # noqa: PLC0415
            conn = get_connection()
            cursor = conn.execute(
                "SELECT id, name FROM tournaments WHERE status = 'active' ORDER BY created_at DESC"
            )
            active_tournaments = [dict(row) for row in cursor.fetchall()]
            cursor2 = conn.execute(
                """
                SELECT a.name,
                       COALESCE(SUM(s.points), 0) AS total_points
                FROM archers a
                LEFT JOIN scores s ON s.archer_id = a.id
                LEFT JOIN tournaments t ON t.id = s.tournament_id AND t.status = 'finished'
                GROUP BY a.id, a.name
                ORDER BY total_points DESC, a.name ASC
                LIMIT 5
                """
            )
            top_archers = [dict(row) for row in cursor2.fetchall()]
        except Exception:
            active_tournaments = []
            top_archers = []
        club = get_club_settings()
        active_news = get_active_news()
        if active_news:
            ticker = " · ".join(
                f"📢 {n['title']}: {n['content']}" for n in active_news
            )
        else:
            ticker = club.get("ticker_text", "🏹 Bienvenido")
        return render_template("home.html",
                               active_tournaments=active_tournaments,
                               top_archers=top_archers,
                               club=club,
                               ticker=ticker)

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
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            info["tables"] = [r[0] for r in cursor.fetchall()]
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
