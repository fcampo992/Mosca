"""
Fixtures compartidos para todos los tests de KiroArchery.

Proporciona:
  - app: instancia Flask en modo TESTING con SQLite :memory:.
  - db_conn: conexion SQLite :memory: activa durante cada test.
  - sample_tournament: torneo de prueba con status='created'.
  - active_tournament: torneo de prueba con status='active'.
  - authenticated_archer: arquero de prueba insertado en la DB.
  - enrolled_archer: arquero inscrito en el torneo activo con categoria.
"""

import os
import sqlite3
import uuid

import pytest
from unittest.mock import patch

from archer.app import create_app
from archer.db import init_db


class TestingConfig:
    """Configuracion minima para tests: DB en memoria, sin SECRET_KEY obligatorio."""

    TESTING = True
    SECRET_KEY = "test-secret-key"
    # La conexion de test se inyecta directamente en DB_CONN
    # para evitar que get_connection() intente Turso.


@pytest.fixture(scope="function")
def app():
    """Crea una app Flask de test con SQLite :memory: y esquema inicializado.

    Las variables de entorno de Turso se eliminan temporalmente para que
    create_app() use SQLite local durante la inicializacion y no intente
    conectar a Turso (que no esta disponible en el entorno de test).
    Luego se reemplaza la conexion por una instancia :memory: limpia.
    """
    env_patch = patch.dict(
        os.environ,
        {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""},
        clear=False,
    )
    with env_patch:
        flask_app = create_app(TestingConfig)

    # Crear conexion in-memory y sobreescribir el singleton
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    with flask_app.app_context():
        flask_app.config["DB_CONN"] = conn
        init_db(conn)
        yield flask_app

    conn.close()


@pytest.fixture(scope="function")
def db_conn(app):
    """Retorna la conexion SQLite :memory: activa para el test."""
    with app.app_context():
        yield app.config["DB_CONN"]


@pytest.fixture(scope="function")
def sample_tournament(db_conn):
    """Inserta un torneo con status='created' y retorna su dict."""
    tournament_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (tournament_id, "Torneo Test", "2025-06-01", "created"),
    )
    db_conn.commit()
    return {
        "id": tournament_id,
        "name": "Torneo Test",
        "date": "2025-06-01",
        "status": "created",
    }


@pytest.fixture(scope="function")
def active_tournament(db_conn):
    """Inserta un torneo con status='active' y retorna su dict."""
    tournament_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (tournament_id, "Torneo Activo Test", "2025-07-01", "active"),
    )
    db_conn.commit()
    return {
        "id": tournament_id,
        "name": "Torneo Activo Test",
        "date": "2025-07-01",
        "status": "active",
    }


@pytest.fixture(scope="function")
def authenticated_archer(db_conn):
    """Inserta un arquero de prueba y retorna su dict."""
    archer_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, "1234", "Arquero Test"),
    )
    db_conn.commit()
    return {
        "id": archer_id,
        "pin": "1234",
        "name": "Arquero Test",
    }


@pytest.fixture(scope="function")
def enrolled_archer(db_conn, authenticated_archer, active_tournament):
    """Inscribe al arquero de prueba en el torneo activo con una categoria.

    Retorna un dict con claves: archer, tournament, category, registration_id.
    """
    category_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) "
        "VALUES (?, ?, ?, ?, ?)",
        (category_id, active_tournament["id"], "Recurvo", "70m", "Masculino"),
    )
    registration_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO registrations (id, tournament_id, archer_id, category_id) "
        "VALUES (?, ?, ?, ?)",
        (registration_id, active_tournament["id"], authenticated_archer["id"], category_id),
    )
    db_conn.commit()
    return {
        "archer": authenticated_archer,
        "tournament": active_tournament,
        "category": {
            "id": category_id,
            "tournament_id": active_tournament["id"],
            "bow_type": "Recurvo",
            "distance": "70m",
            "gender": "Masculino",
        },
        "registration_id": registration_id,
    }
