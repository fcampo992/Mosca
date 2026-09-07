"""
DB_Module — conexión singleton e inicialización de tablas.

Implementa:
  - get_connection(): patrón singleton vía app.config['DB_CONN'].
      * Si TURSO_DATABASE_URL y TURSO_AUTH_TOKEN están definidas, intenta
        conectar a Turso con turso_serverless (HTTP, sin conexiones persistentes).
      * Si las variables no están definidas, usa sqlite3.
      * Si la conexión Turso falla, usa SQLite en /tmp como fallback (DATOS NO PERSISTIRÁN).
  - init_db(conn): ejecuta los cinco CREATE TABLE IF NOT EXISTS del esquema.
"""

import logging
import os
import sqlite3
import sys

from flask import current_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _connect_turso(url: str, token: str):
    """Conecta a Turso con turso_serverless (DB-API 2.0 nativo). Retorna la conexión o None."""
    try:
        import turso_serverless  # type: ignore
    except ImportError as exc:
        logger.error("turso_serverless no está instalado: %s", exc)
        return None

    try:
        conn = turso_serverless.connect(url, auth_token=token)
        # Configurar row_factory para que dict(row) funcione igual que con sqlite3
        conn.row_factory = turso_serverless.Row
        logger.info("Conexión a Turso establecida.")
        return conn
    except Exception as exc:
        logger.error("Error al conectar a Turso: %s", exc, exc_info=True)
        return None


def _connect_sqlite() -> sqlite3.Connection:
    """Crea y retorna una conexión SQLite usando /tmp (requerido en Vercel)."""
    # En Vercel/Lambda el filesystem es read-only excepto /tmp
    db_path = "/tmp/db.sqlite3"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get_connection():
    """Retorna la conexión activa (Turso o SQLite). Patrón singleton."""
    conn = current_app.config.get("DB_CONN")
    if conn is not None:
        return conn

    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")

    if turso_url and turso_token:
        logger.info("Conectando a Turso: %s", turso_url)
        conn = _connect_turso(turso_url, turso_token)
        if conn is None:
            logger.error("Turso falló — usando SQLite /tmp como fallback. DATOS NO PERSISTIRÁN.")
            conn = _connect_sqlite()
        else:
            logger.info("Conexión a Turso establecida correctamente.")
    else:
        logger.info("Variables de entorno Turso no definidas. Usando SQLite local.")
        conn = _connect_sqlite()

    current_app.config["DB_CONN"] = conn
    return conn


def init_db(conn) -> None:
    """Ejecuta los cinco CREATE TABLE IF NOT EXISTS del esquema KiroArchery.

    Acepta tanto conexiones turso_serverless como sqlite3; ambas exponen
    el método `execute()` compatible con DB-API 2.0.
    """
    statements = [
        """
        CREATE TABLE IF NOT EXISTS archers (
            id         TEXT PRIMARY KEY,
            pin        TEXT UNIQUE NOT NULL,
            name       TEXT NOT NULL,
            photo_url  TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tournaments (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            date            TEXT NOT NULL,
            status          TEXT CHECK(status IN ('created', 'active', 'finished'))
                            DEFAULT 'created',
            rounds          INTEGER NOT NULL DEFAULT 10,
            arrows_per_end  INTEGER NOT NULL DEFAULT 5,
            rounds_count    INTEGER NOT NULL DEFAULT 1,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS categories (
            id            TEXT PRIMARY KEY,
            tournament_id TEXT NOT NULL,
            bow_type      TEXT NOT NULL,
            distance      TEXT NOT NULL,
            gender        TEXT NOT NULL,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id            TEXT PRIMARY KEY,
            tournament_id TEXT NOT NULL,
            archer_id     TEXT NOT NULL,
            category_id   TEXT NOT NULL,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
            FOREIGN KEY (archer_id)     REFERENCES archers(id),
            FOREIGN KEY (category_id)   REFERENCES categories(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scores (
            id            TEXT PRIMARY KEY,
            tournament_id TEXT NOT NULL,
            archer_id     TEXT NOT NULL,
            round_number  INTEGER NOT NULL,
            end_number    INTEGER NOT NULL,
            arrow_val     TEXT NOT NULL,
            points        INTEGER NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
            FOREIGN KEY (archer_id)     REFERENCES archers(id)
        )
        """,
    ]

    for statement in statements:
        try:
            conn.execute(statement)
        except Exception as e:
            logger.error("Error en CREATE TABLE: %s | SQL: %s", e, statement[:80])

    try:
        conn.commit()
    except Exception as e:
        logger.debug("commit tras DDL: %s", e)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS club_settings (
            id              TEXT PRIMARY KEY DEFAULT 'default',
            club_name       TEXT NOT NULL DEFAULT 'KiroArchery',
            hero_title      TEXT NOT NULL DEFAULT 'Tu torneo de arquería, en tiempo real',
            hero_subtitle   TEXT NOT NULL DEFAULT 'Cargá flechas, seguí el leaderboard en vivo y consultá el ranking histórico.',
            ticker_text     TEXT NOT NULL DEFAULT '🏹 Bienvenido · Registrá tu puntaje · ¡Buena puntería!',
            color_from      TEXT NOT NULL DEFAULT '#166534',
            color_to        TEXT NOT NULL DEFAULT '#16a34a',
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO club_settings (id) VALUES ('default')
        """
    )
    try:
        conn.commit()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Migraciones seguras: añadir columnas nuevas a tablas existentes.
    # Se ejecutan dentro de try/except para tolerar el caso en que la
    # columna ya exista (OperationalError: duplicate column name).
    # -----------------------------------------------------------------------
    migrations = [
        "ALTER TABLE tournaments ADD COLUMN rounds INTEGER NOT NULL DEFAULT 10",
        "ALTER TABLE tournaments ADD COLUMN arrows_per_end INTEGER NOT NULL DEFAULT 6",
        "ALTER TABLE tournaments ADD COLUMN rounds_count INTEGER NOT NULL DEFAULT 1",
    ]
    for migration in migrations:
        try:
            conn.execute(migration)
        except Exception:
            # La columna ya existe; no hay nada que hacer.
            pass

    try:
        conn.commit()
    except Exception:
        pass

    logger.info("Esquema de base de datos inicializado correctamente.")
