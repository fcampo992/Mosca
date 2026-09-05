"""
archer/config.py

Reads environment variables and exposes a Config class consumed by create_app().
No defaults are provided for secrets — the application will raise at startup if
SESSION_SECRET is missing, which is intentional to catch misconfigured deploys early.
"""

import os


class Config:
    # ── Turso / libsql-experimental ────────────────────────────────────────────────────────
    # When both are set the DB_Module will attempt a Turso connection.
    # When either is absent the DB_Module falls back to a local SQLite file.
    TURSO_DATABASE_URL: str | None = os.environ.get("TURSO_DATABASE_URL")
    TURSO_AUTH_TOKEN: str | None = os.environ.get("TURSO_AUTH_TOKEN")

    # ── Flask session security ──────────────────────────────────────────────────────────────
    # Must be set in the environment; no hard-coded fallback for security.
    SECRET_KEY: str = os.environ.get("SESSION_SECRET", "")

    # ── Admin credentials ──────────────────────────────────────────────────────────────────
    # Read from environment variables; never hard-coded in source.
    # ADMIN_PASSWORD should always be set to a strong value in production.
    ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")

    # ── Flask internals ────────────────────────────────────────────────────────────────────
    TESTING: bool = False
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "0") == "1"
