"""
DB_Module — conexión singleton e inicialización de tablas.
"""

import logging
import os
import sqlite3
import sys

from flask import current_app

# Logging al root para que Vercel capture todos los mensajes independientemente del handler
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

# Import al nivel del módulo para evitar overhead y detectar fallo de instalación al arrancar
try:
    import turso_serverless as _turso  # type: ignore
    logger.info("turso_serverless disponible, versión: %s", getattr(_turso, "__version__", "?"))
except ImportError:
    _turso = None  # type: ignore
    logger.warning("turso_serverless no está instalado — se usará SQLite como fallback")


class _DictRow(dict):
    """Row compatible con sqlite3.Row: soporta dict(row), row['col'] y row[idx]."""

    def __init__(self, cursor, row):
        keys = [col[0] for col in cursor.description]
        super().__init__(zip(keys, row))
        self._data = row

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[key]
        return super().__getitem__(key)

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _connect_turso(url: str, token: str):
    """Conecta a Turso con turso_serverless (DB-API 2.0 nativo). Retorna la conexión o None."""
    if _turso is None:
        logger.error("turso_serverless no disponible")
        return None

    logger.info("Llamando a turso_serverless.connect...")
    try:
        conn = _turso.connect(url, auth_token=token)
        # _DictRow: soporta dict(row), row['col'] Y row[idx] — compatible con todo el código
        conn.row_factory = _DictRow
        logger.info("turso_serverless.connect OK — tipo: %s", type(conn).__name__)
        return conn
    except Exception as exc:
        logger.error("turso_serverless.connect falló: %s", exc, exc_info=True)
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
    logger.info("get_connection() llamada")
    conn = current_app.config.get("DB_CONN")
    if conn is not None:
        logger.info("Reutilizando conexión existente: %s", type(conn).__name__)
        return conn

    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    logger.info("TURSO_URL presente=%s, TURSO_TOKEN presente=%s", bool(turso_url), bool(turso_token))

    if turso_url and turso_token:
        logger.info("Intentando conectar a Turso...")
        conn = _connect_turso(turso_url, turso_token)
        if conn is None:
            logger.error("_connect_turso retornó None — fallback a SQLite /tmp")
            conn = _connect_sqlite()
        else:
            logger.info("Conexión Turso lista: %s", type(conn).__name__)
    else:
        logger.info("Sin credenciales Turso — usando SQLite /tmp")
        conn = _connect_sqlite()

    logger.info("Guardando conexión en app.config: %s", type(conn).__name__)
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
            pass

    try:
        conn.commit()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Perfil extendido del arquero (datos personales editables)
    # -----------------------------------------------------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archer_profiles (
            archer_id       TEXT PRIMARY KEY,
            nickname        TEXT,
            club            TEXT,
            dominant_hand   TEXT CHECK(dominant_hand IN ('Diestro', 'Zurdo')) DEFAULT 'Diestro',
            bow_category    TEXT,
            season_goal     TEXT,
            banner_url      TEXT,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (archer_id) REFERENCES archers(id)
        )
        """
    )

    # -----------------------------------------------------------------------
    # Setups de equipo del arquero
    # -----------------------------------------------------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bow_setups (
            id              TEXT PRIMARY KEY,
            archer_id       TEXT NOT NULL,
            name            TEXT NOT NULL,
            bow_type        TEXT NOT NULL,
            draw_weight     REAL,
            draw_length     REAL,
            string_material TEXT,
            arrow_model     TEXT,
            arrow_spine     TEXT,
            arrow_length    REAL,
            point_weight    INTEGER,
            vanes           TEXT,
            nock            TEXT,
            sight_marks     TEXT,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (archer_id) REFERENCES archers(id)
        )
        """
    )
    try:
        conn.commit()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Entrenamientos independientes
    # -----------------------------------------------------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS training_sessions (
            id              TEXT PRIMARY KEY,
            archer_id       TEXT NOT NULL,
            bow_setup_id    TEXT,
            mode            TEXT NOT NULL DEFAULT 'scored',
            distance        TEXT NOT NULL DEFAULT '18m',
            target_face     TEXT,
            environment     TEXT CHECK(environment IN ('indoor', 'outdoor')) DEFAULT 'indoor',
            arrows_per_end  INTEGER NOT NULL DEFAULT 6,
            total_ends      INTEGER,
            session_date    TEXT NOT NULL,
            notes           TEXT,
            status          TEXT CHECK(status IN ('active', 'finished')) DEFAULT 'active',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (archer_id)    REFERENCES archers(id),
            FOREIGN KEY (bow_setup_id) REFERENCES bow_setups(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS training_ends (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL,
            end_number  INTEGER NOT NULL,
            scores_json TEXT NOT NULL DEFAULT '[]',
            note        TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES training_sessions(id)
        )
        """
    )
    try:
        conn.commit()
    except Exception:
        pass

    logger.info("Esquema de base de datos inicializado correctamente.")
