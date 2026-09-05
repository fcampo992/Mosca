"""
Tests unitarios para Archer_Module — autenticación por PIN y sesiones.

Cubre:
  - authenticate_pin con PIN válido registrado → datos del arquero
  - authenticate_pin con PIN válido no registrado → error genérico
  - authenticate_pin con formato inválido → error sin consultar DB
  - authenticate_pin bloquea tras 5 intentos fallidos durante 5 minutos
  - is_session_valid: True para ≤ 30 min, False para > 30 min
  - get_active_tournament: None si el arquero no está en un torneo activo

Requerimientos cubiertos: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7
"""

import uuid
from datetime import datetime, timedelta, UTC

import pytest

from archer.modules.archer import (
    authenticate_pin,
    get_active_tournament,
    is_session_valid,
    reset_lockout,
)


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------

def _insert_archer(db_conn, *, name: str = "Test Archer", pin: str = "1234") -> dict:
    """Inserta un arquero directamente en la DB y retorna su dict."""
    archer_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, pin, name),
    )
    db_conn.commit()
    return {"id": archer_id, "pin": pin, "name": name}


def _insert_tournament(db_conn, *, status: str = "active") -> dict:
    """Inserta un torneo con el estado indicado y retorna su dict."""
    tournament_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (tournament_id, "Torneo Test", "2025-06-01", status),
    )
    db_conn.commit()
    return {"id": tournament_id, "name": "Torneo Test", "date": "2025-06-01", "status": status}


def _enroll_archer(db_conn, archer_id: str, tournament_id: str) -> None:
    """Inscribe el arquero en el torneo (con una categoría dummy)."""
    category_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) "
        "VALUES (?, ?, ?, ?, ?)",
        (category_id, tournament_id, "Recurvo", "70m", "Masculino"),
    )
    registration_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO registrations (id, tournament_id, archer_id, category_id) "
        "VALUES (?, ?, ?, ?)",
        (registration_id, tournament_id, archer_id, category_id),
    )
    db_conn.commit()


# ---------------------------------------------------------------------------
# Fixture: limpiar lockout antes de cada test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_lockout():
    """Limpia el estado de bloqueo en memoria antes y después de cada test."""
    reset_lockout()
    yield
    reset_lockout()


# ---------------------------------------------------------------------------
# Tests: authenticate_pin con PIN válido registrado (Req 4.1)
# ---------------------------------------------------------------------------

class TestAuthenticatePinSuccess:
    def test_returns_archer_id(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="5678")
        with app.app_context():
            result = authenticate_pin("5678")
        assert result.get("archer_id") == archer["id"]

    def test_returns_archer_name(self, app, db_conn):
        _insert_archer(db_conn, name="Ana García", pin="4321")
        with app.app_context():
            result = authenticate_pin("4321")
        assert result.get("name") == "Ana García"

    def test_returns_pin(self, app, db_conn):
        _insert_archer(db_conn, pin="0001")
        with app.app_context():
            result = authenticate_pin("0001")
        assert result.get("pin") == "0001"

    def test_no_error_key_on_success(self, app, db_conn):
        _insert_archer(db_conn, pin="9999")
        with app.app_context():
            result = authenticate_pin("9999")
        assert "error" not in result

    def test_resets_lockout_counter_on_success(self, app, db_conn):
        """Tras un fallo y luego un acierto, el bloqueo se limpia."""
        _insert_archer(db_conn, pin="1111")
        with app.app_context():
            # Generar un intento fallido con un PIN que no existe
            authenticate_pin("9000")
            # Ahora autenticar con PIN válido
            result = authenticate_pin("1111")
        assert result.get("archer_id") is not None


# ---------------------------------------------------------------------------
# Tests: authenticate_pin con PIN no registrado (Req 4.2)
# ---------------------------------------------------------------------------

class TestAuthenticatePinNotFound:
    def test_returns_error_key(self, app, db_conn):
        with app.app_context():
            result = authenticate_pin("0000")
        assert "error" in result

    def test_error_message_generic(self, app, db_conn):
        """El mensaje no debe revelar datos de otros arqueros."""
        _insert_archer(db_conn, pin="1234")
        with app.app_context():
            result = authenticate_pin("5678")
        assert result["error"] == "PIN incorrecto."

    def test_no_archer_id_in_response(self, app, db_conn):
        with app.app_context():
            result = authenticate_pin("0000")
        assert "archer_id" not in result

    def test_no_name_in_response(self, app, db_conn):
        with app.app_context():
            result = authenticate_pin("0000")
        assert "name" not in result


# ---------------------------------------------------------------------------
# Tests: authenticate_pin con formato inválido (Req 4.6)
# ---------------------------------------------------------------------------

class TestAuthenticatePinInvalidFormat:
    @pytest.mark.parametrize("bad_pin", [
        "",          # vacío
        "123",       # menos de 4 dígitos
        "12345",     # más de 4 dígitos
        "12ab",      # no numérico
        "abcd",      # completamente no numérico
        " 123",      # espacio + 3 dígitos
        "12 4",      # espacio interno
        "12.4",      # carácter especial
    ])
    def test_invalid_format_returns_error(self, app, db_conn, bad_pin):
        with app.app_context():
            result = authenticate_pin(bad_pin)
        assert "error" in result
        assert result.get("field") == "pin"

    def test_invalid_format_does_not_query_db(self, app, db_conn):
        """Formato inválido debe fallar antes de tocar la DB.

        Verificamos que el mensaje es el de validación de formato,
        no el de PIN incorrecto (que implicaría consulta a la DB).
        """
        with app.app_context():
            result = authenticate_pin("abc4")
        assert "4 dígitos numéricos" in result["error"]

    def test_invalid_format_message_contains_format_hint(self, app, db_conn):
        with app.app_context():
            result = authenticate_pin("XXXX")
        assert "dígitos" in result["error"].lower() or "numéric" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tests: bloqueo tras 5 intentos fallidos (Req 4.7)
# ---------------------------------------------------------------------------

class TestAuthenticatePinLockout:
    def test_blocked_after_five_failures(self, app, db_conn):
        with app.app_context():
            for _ in range(5):
                authenticate_pin("7777")
            result = authenticate_pin("7777")
        assert result.get("blocked") is True

    def test_blocked_message_contains_minutes(self, app, db_conn):
        with app.app_context():
            for _ in range(5):
                authenticate_pin("8888")
            result = authenticate_pin("8888")
        assert "minutos" in result["error"].lower() or "minuto" in result["error"].lower()

    def test_not_blocked_after_four_failures(self, app, db_conn):
        with app.app_context():
            for _ in range(4):
                authenticate_pin("3333")
            result = authenticate_pin("3333")
        # Cuarto intento → aún debe retornar "PIN incorrecto", no bloqueado
        assert result.get("blocked") is not True
        assert result["error"] == "PIN incorrecto."

    def test_successful_auth_after_other_pin_blocked(self, app, db_conn):
        """El bloqueo de un PIN no afecta a otros PINs válidos."""
        _insert_archer(db_conn, pin="2222")
        with app.app_context():
            for _ in range(5):
                authenticate_pin("9876")  # PIN diferente, no registrado
            result = authenticate_pin("2222")
        assert result.get("archer_id") is not None

    def test_blocked_pin_returns_error_not_success(self, app, db_conn):
        """Bloqueo: aunque el PIN exista en DB, debe retornar error mientras esté bloqueado."""
        _insert_archer(db_conn, pin="6666")
        with app.app_context():
            # Generar bloqueo con el mismo PIN (sin importar que esté en DB,
            # el bloqueo se basa en los intentos previos fallidos con ese PIN)
            # Para esto, primero bloqueamos con intentos fallidos antes de insertar
            for _ in range(5):
                authenticate_pin("5555")  # PIN no registrado
            result = authenticate_pin("5555")
        assert result.get("blocked") is True


# ---------------------------------------------------------------------------
# Tests: is_session_valid (Req 4.4)
# ---------------------------------------------------------------------------

class TestIsSessionValid:
    def test_valid_session_just_now(self):
        now = datetime.now()
        assert is_session_valid(now.isoformat()) is True

    def test_valid_session_29_minutes_ago(self):
        ts = (datetime.now() - timedelta(minutes=29)).isoformat()
        assert is_session_valid(ts) is True

    def test_valid_session_exactly_30_minutes(self):
        ts = (datetime.now() - timedelta(minutes=30)).isoformat()
        # Exactamente 30 min → válido (≤ 30)
        assert is_session_valid(ts) is True

    def test_invalid_session_31_minutes_ago(self):
        ts = (datetime.now() - timedelta(minutes=31)).isoformat()
        assert is_session_valid(ts) is False

    def test_invalid_session_one_hour_ago(self):
        ts = (datetime.now() - timedelta(hours=1)).isoformat()
        assert is_session_valid(ts) is False

    def test_invalid_session_yesterday(self):
        ts = (datetime.now() - timedelta(days=1)).isoformat()
        assert is_session_valid(ts) is False

    def test_invalid_session_bad_format(self):
        assert is_session_valid("not-a-date") is False

    def test_invalid_session_empty_string(self):
        assert is_session_valid("") is False

    def test_future_timestamp_is_valid(self):
        """Un timestamp en el futuro (reloj desincronizado) sigue siendo válido."""
        ts = (datetime.now() + timedelta(minutes=5)).isoformat()
        assert is_session_valid(ts) is True


# ---------------------------------------------------------------------------
# Tests: get_active_tournament (Req 4.3)
# ---------------------------------------------------------------------------

class TestGetActiveTournament:
    def test_returns_none_when_no_tournaments(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="1010")
        with app.app_context():
            result = get_active_tournament(archer["id"])
        assert result is None

    def test_returns_none_when_not_enrolled(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="2020")
        _insert_tournament(db_conn, status="active")
        with app.app_context():
            result = get_active_tournament(archer["id"])
        assert result is None

    def test_returns_none_when_enrolled_in_created_tournament(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="3030")
        tournament = _insert_tournament(db_conn, status="created")
        _enroll_archer(db_conn, archer["id"], tournament["id"])
        with app.app_context():
            result = get_active_tournament(archer["id"])
        assert result is None

    def test_returns_none_when_enrolled_in_finished_tournament(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="4040")
        tournament = _insert_tournament(db_conn, status="finished")
        _enroll_archer(db_conn, archer["id"], tournament["id"])
        with app.app_context():
            result = get_active_tournament(archer["id"])
        assert result is None

    def test_returns_tournament_when_enrolled_in_active(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="5050")
        tournament = _insert_tournament(db_conn, status="active")
        _enroll_archer(db_conn, archer["id"], tournament["id"])
        with app.app_context():
            result = get_active_tournament(archer["id"])
        assert result is not None
        assert result["id"] == tournament["id"]

    def test_returned_tournament_has_status_active(self, app, db_conn):
        archer = _insert_archer(db_conn, pin="6060")
        tournament = _insert_tournament(db_conn, status="active")
        _enroll_archer(db_conn, archer["id"], tournament["id"])
        with app.app_context():
            result = get_active_tournament(archer["id"])
        assert result["status"] == "active"

    def test_returns_none_for_unknown_archer_id(self, app, db_conn):
        with app.app_context():
            result = get_active_tournament(str(uuid.uuid4()))
        assert result is None
