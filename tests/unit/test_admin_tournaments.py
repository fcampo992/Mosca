"""
Tests unitarios para las funciones de torneos del Admin_Module.

Cubre Requerimientos 2.1, 2.2, 2.6, 2.7, 2.8, 2.9:
  - create_tournament(): validaciones de nombre y fecha, persistencia, retorno.
  - list_tournaments(): ordenamiento DESC por created_at.
  - change_tournament_status(): máquina de estados completa.
"""

import time
import uuid

import pytest

from archer.modules.admin import (
    change_tournament_status,
    create_tournament,
    list_tournaments,
)


# ---------------------------------------------------------------------------
# create_tournament — Req 2.2: validaciones
# ---------------------------------------------------------------------------

class TestCreateTournamentValidation:
    def test_empty_name_returns_error_with_field(self, app):
        with app.app_context():
            result = create_tournament(name="", date="2025-06-01")
        assert "error" in result
        assert result.get("field") == "name"

    def test_name_over_150_chars_returns_error_with_field(self, app):
        long_name = "A" * 151
        with app.app_context():
            result = create_tournament(name=long_name, date="2025-06-01")
        assert "error" in result
        assert result.get("field") == "name"

    def test_name_exactly_150_chars_is_accepted(self, app):
        name = "B" * 150
        with app.app_context():
            result = create_tournament(name=name, date="2025-06-01")
        assert "error" not in result

    def test_invalid_date_format_returns_error_with_field(self, app):
        bad_dates = ["01-06-2025", "2025/06/01", "20250601", "june 1 2025", ""]
        with app.app_context():
            for bad_date in bad_dates:
                result = create_tournament(name="Torneo Válido", date=bad_date)
                assert "error" in result, f"Esperaba error para fecha: {bad_date!r}"
                assert result.get("field") == "date", f"Esperaba field='date' para: {bad_date!r}"

    def test_invalid_date_does_not_insert_record(self, app, db_conn):
        with app.app_context():
            create_tournament(name="Torneo Inválido", date="01/06/2025")
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM tournaments WHERE name = ?", ("Torneo Inválido",)
        )
        assert cursor.fetchone()[0] == 0

    def test_empty_name_does_not_insert_record(self, app, db_conn):
        with app.app_context():
            create_tournament(name="", date="2025-06-01")
        cursor = db_conn.execute("SELECT COUNT(*) FROM tournaments")
        assert cursor.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# create_tournament — Req 2.1: creación exitosa
# ---------------------------------------------------------------------------

class TestCreateTournamentSuccess:
    def test_returns_dict_with_all_fields(self, app):
        with app.app_context():
            result = create_tournament(name="Copa Primavera", date="2025-09-15")
        assert "error" not in result
        assert result["name"] == "Copa Primavera"
        assert result["date"] == "2025-09-15"
        assert result["status"] == "created"
        assert "id" in result
        assert "created_at" in result

    def test_returned_id_is_valid_uuid_v4(self, app):
        with app.app_context():
            result = create_tournament(name="Copa Otoño", date="2025-10-01")
        parsed = uuid.UUID(result["id"])
        assert parsed.version == 4

    def test_status_is_created_on_insert(self, app):
        with app.app_context():
            result = create_tournament(name="Torneo A", date="2025-01-15")
        assert result["status"] == "created"

    def test_tournament_is_persisted_in_db(self, app, db_conn):
        with app.app_context():
            result = create_tournament(name="Torneo Persistente", date="2025-03-20")
        cursor = db_conn.execute(
            "SELECT id, name, date, status FROM tournaments WHERE id = ?",
            (result["id"],),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["name"] == "Torneo Persistente"
        assert row["date"] == "2025-03-20"
        assert row["status"] == "created"

    def test_name_with_exactly_1_char_is_accepted(self, app):
        with app.app_context():
            result = create_tournament(name="X", date="2025-06-01")
        assert "error" not in result
        assert result["name"] == "X"


# ---------------------------------------------------------------------------
# list_tournaments — Req 2.9: ordenamiento DESC por created_at
# ---------------------------------------------------------------------------

class TestListTournaments:
    def test_returns_empty_list_when_no_tournaments(self, app):
        with app.app_context():
            result = list_tournaments()
        assert result == []

    def test_returns_all_tournaments(self, app, db_conn):
        for i in range(3):
            db_conn.execute(
                "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), f"Torneo {i}", "2025-01-01", "created"),
            )
        db_conn.commit()

        with app.app_context():
            result = list_tournaments()
        assert len(result) == 3

    def test_returns_plain_dicts(self, app, db_conn):
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "Torneo Dict", "2025-01-01", "created"),
        )
        db_conn.commit()

        with app.app_context():
            result = list_tournaments()

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)

    def test_ordered_by_created_at_desc(self, app, db_conn):
        """Los torneos deben aparecer con el más reciente primero."""
        ids = []
        for i in range(3):
            tid = str(uuid.uuid4())
            ids.append(tid)
            db_conn.execute(
                "INSERT INTO tournaments (id, name, date, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (tid, f"Torneo {i}", "2025-01-01", "created", f"2025-01-0{i + 1} 10:00:00"),
            )
        db_conn.commit()

        with app.app_context():
            result = list_tournaments()

        assert len(result) == 3
        # El más reciente (created_at = 2025-01-03) debe ir primero
        assert result[0]["id"] == ids[2]
        assert result[1]["id"] == ids[1]
        assert result[2]["id"] == ids[0]


# ---------------------------------------------------------------------------
# change_tournament_status — Req 2.6, 2.7, 2.8: máquina de estados
# ---------------------------------------------------------------------------

class TestChangeTournamentStatus:
    def _insert_tournament(self, db_conn, status: str) -> str:
        tid = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (tid, "Torneo Estado", "2025-06-01", status),
        )
        db_conn.commit()
        return tid

    # ── Transiciones válidas ──────────────────────────────────────────────

    def test_created_to_active_succeeds(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "created")
        with app.app_context():
            result = change_tournament_status(tid, "active")
        assert "error" not in result
        assert result["status"] == "active"

    def test_active_to_finished_succeeds(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "active")
        with app.app_context():
            result = change_tournament_status(tid, "finished")
        assert "error" not in result
        assert result["status"] == "finished"

    def test_success_persists_new_status_in_db(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "created")
        with app.app_context():
            change_tournament_status(tid, "active")
        cursor = db_conn.execute(
            "SELECT status FROM tournaments WHERE id = ?", (tid,)
        )
        assert cursor.fetchone()["status"] == "active"

    def test_returns_updated_tournament_dict(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "created")
        with app.app_context():
            result = change_tournament_status(tid, "active")
        assert result["id"] == tid
        assert result["status"] == "active"
        assert "name" in result
        assert "date" in result

    # ── Transiciones inválidas (Req 2.8) ─────────────────────────────────

    def test_finished_to_created_returns_error(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "finished")
        with app.app_context():
            result = change_tournament_status(tid, "created")
        assert "error" in result
        assert "finished" in result["error"]
        assert "created" in result["error"]

    def test_finished_to_active_returns_error(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "finished")
        with app.app_context():
            result = change_tournament_status(tid, "active")
        assert "error" in result
        assert "finished" in result["error"]
        assert "active" in result["error"]

    def test_active_to_created_returns_error(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "active")
        with app.app_context():
            result = change_tournament_status(tid, "created")
        assert "error" in result
        assert "active" in result["error"]
        assert "created" in result["error"]

    def test_invalid_transition_does_not_modify_status(self, app, db_conn):
        tid = self._insert_tournament(db_conn, "finished")
        with app.app_context():
            change_tournament_status(tid, "created")
        cursor = db_conn.execute(
            "SELECT status FROM tournaments WHERE id = ?", (tid,)
        )
        assert cursor.fetchone()["status"] == "finished"

    # ── Torneo no encontrado ──────────────────────────────────────────────

    def test_nonexistent_tournament_returns_error(self, app):
        with app.app_context():
            result = change_tournament_status(str(uuid.uuid4()), "active")
        assert "error" in result
        assert "no encontrado" in result["error"].lower()
