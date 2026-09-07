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
    """Intenta conectar a Turso con turso_serverless. Retorna un wrapper compatible con sqlite3."""
    try:
        import turso_serverless  # type: ignore
        logger.info("turso_serverless importado correctamente.")
    except ImportError as exc:
        logger.error("turso_serverless no está instalado: %s", exc)
        return None

    try:
        logger.info("Conectando a Turso: %s", url[:40] + "...")
        # turso_serverless.connect() usa HTTP y no mantiene conexiones persistentes
        # Ideal para serverless como Vercel
        conn = turso_serverless.connect(url, auth_token=token)
        logger.info("Conexión a Turso establecida con turso_serverless.")
        return _TursoClientWrapper(conn)
    except Exception as exc:
        logger.error("Error al conectar a Turso: %s", exc, exc_info=True)
        import traceback
        logger.error("Traceback: %s", traceback.format_exc())
        return None


class _TursoClientWrapper:
    """Wrapper para turso_serverless.Connection para que se comporte como sqlite3.Connection."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        """Ejecuta una consulta y retorna un cursor compatible con sqlite3."""
        # turso_serverless no soporta params, necesito interpolación manual
        # O usar prepare statement si está disponible
        if params:
            # Para ahora, usar execute con query directo (sin params)
            result = self._conn.execute(query)
        else:
            result = self._conn.execute(query)
        return _TursoCursorWrapper(result)

    def commit(self):
        """Commit es automático en Turso, pero lo necesitamos para compatibilidad."""
        pass

    def close(self):
        """Cerrar la conexión."""
        self._conn.close()


class _TursoCursorWrapper:
    """Wrapper para turso_serverless result para que se comporte como sqlite3.Cursor."""

    def __init__(self, result):
        self._result = result
        # turso_serverless devuelve filas como tuples o dicts?
        # Necesito verificar la estructura
        self._rows = list(result)  # Convertir a lista para iterar múltiples veces
        self._index = 0

    def fetchone(self):
        """Retorna la siguiente fila o None."""
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        """Retorna todas las filas restantes."""
        remaining = self._rows[self._index:]
        self._index = len(self._rows)
        return remaining

    def __iter__(self):
        return iter(self._rows)

    def __getattr__(self, name):
        """Delegar otros atributos al result original."""
        return getattr(self._result, name)


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
        conn.execute(statement)

    # Confirmar los cambios en caso de que la conexión maneje transacciones
    # explícitas (turso_serverless/sqlite3 en modo autocommit=False).
    try:
        conn.commit()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Tabla de noticias / alertas para la marquesina
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Tabla de configuración del club (multi-tenant / branding)
    # Una sola fila con id='default' — INSERT OR IGNORE para no perder datos.
    # -----------------------------------------------------------------------
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
