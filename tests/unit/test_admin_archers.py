"""
Tests unitarios para las funciones de arqueros e inscripciones del Admin_Module.

Cubre:
  - create_archer: validaciones de nombre, PIN, unicidad y éxito
  - list_archers: orden alfabético
  - enroll_archer: caso exitoso y todos los casos de error
"""

import uuid

import pytest

from archer.modules.admin import create_archer, enroll_archer, list_archers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_archer(db_conn, name="Juan Pérez", pin="1234"):
    """Inserta un arquero directamente en la DB y retorna su id."""
    archer_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, pin, name),
    )
    db_conn.commit()
    return archer_id


def _insert_category(db_conn, tournament_id, bow_type="Recurvo", distance="70m", gender="Masculino"):
    """Inserta una categoría en el torneo y retorna su id."""
    category_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) VALUES (?, ?, ?, ?, ?)",
        (category_id, tournament_id, bow_type, distance, gender),
    )
    db_conn.commit()
    return category_id


# ---------------------------------------------------------------------------
# create_archer — validación de nombre
# ---------------------------------------------------------------------------

class TestCreateArcherNameValidation:
    def test_empty_name_returns_error(self, app):
        with app.app_context():
            result = create_archer("", "1234")
        assert "error" in result
        assert result.get("field") == "name"

    def test_name_exceeds_100_chars_returns_error(self, app):
        long_name = "A" * 101
        with app.app_context():
            result = create_archer(long_name, "1234")
        assert "error" in result
        assert result.get("field") == "name"

    def test_name_exactly_100_chars_is_valid(self, app, db_conn):
        name = "A" * 100
        with app.app_context():
            result = create_archer(name, "5678")
        assert "error" not in result
        assert result["name"] == name

    def test_name_of_1_char_is_valid(self, app, db_conn):
        with app.app_context():
            result = create_archer("A", "9012")
        assert "error" not in result
        assert result["name"] == "A"


# ---------------------------------------------------------------------------
# create_archer — validación de PIN
# ---------------------------------------------------------------------------

class TestCreateArcherPinValidation:
    def test_pin_with_letters_returns_error(self, app):
        with app.app_context():
            result = create_archer("Test", "12ab")
        assert "error" in result
        assert result.get("field") == "pin"

    def test_pin_too_short_returns_error(self, app):
        with app.app_context():
            result = create_archer("Test", "123")
        assert "error" in result
        assert result.get("field") == "pin"

    def test_pin_too_long_returns_error(self, app):
        with app.app_context():
            result = create_archer("Test", "12345")
        assert "error" in result
        assert result.get("field") == "pin"

    def test_empty_pin_returns_error(self, app):
        with app.app_context():
            result = create_archer("Test", "")
        assert "error" in result
        assert result.get("field") == "pin"

    def test_pin_with_spaces_returns_error(self, app):
        with app.app_context():
            result = create_archer("Test", "12 4")
        assert "error" in result
        assert result.get("field") == "pin"

    def test_pin_with_leading_zeros_is_valid(self, app):
        """PINs como '0001' son válidos — 4 dígitos numéricos incluyendo ceros."""
        with app.app_context():
            result = create_archer("Test", "0001")
        assert "error" not in result

    def test_duplicate_pin_returns_error(self, app, db_conn):
        """Registrar un segundo arquero con el mismo PIN debe fallar."""
        with app.app_context():
            create_archer("Primero", "4321")
            result = create_archer("Segundo", "4321")
        assert "error" in result
        assert result.get("field") == "pin"
        assert "uso" in result["error"].lower()

    def test_duplicate_pin_does_not_create_record(self, app, db_conn):
        """Tras el error de PIN duplicado no debe incrementarse el conteo de arqueros."""
        with app.app_context():
            create_archer("Primero", "7777")
            create_archer("Segundo", "7777")
            count = db_conn.execute(
                "SELECT COUNT(*) FROM archers WHERE pin = '7777'"
            ).fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# create_archer — caso exitoso
# ---------------------------------------------------------------------------

class TestCreateArcherSuccess:
    def test_returns_full_row_dict(self, app):
        with app.app_context():
            result = create_archer("Ana García", "2468")
        assert "error" not in result
        assert result["name"] == "Ana García"
        assert result["pin"] == "2468"
        assert "id" in result
        assert "created_at" in result

    def test_id_is_uuid_v4(self, app):
        with app.app_context():
            result = create_archer("Carlos López", "3579")
        archer_id = result["id"]
        # uuid.UUID lanza ValueError si el formato es inválido
        parsed = uuid.UUID(archer_id, version=4)
        assert str(parsed) == archer_id

    def test_archer_persisted_in_db(self, app, db_conn):
        with app.app_context():
            result = create_archer("María Torres", "8642")
            row = db_conn.execute(
                "SELECT id, name, pin FROM archers WHERE id = ?", (result["id"],)
            ).fetchone()
        assert row is not None
        assert row["name"] == "María Torres"
        assert row["pin"] == "8642"

    def test_name_validation_error_does_not_create_record(self, app, db_conn):
        with app.app_context():
            create_archer("", "1111")
            count = db_conn.execute(
                "SELECT COUNT(*) FROM archers WHERE pin = '1111'"
            ).fetchone()[0]
        assert count == 0

    def test_pin_validation_error_does_not_create_record(self, app, db_conn):
        with app.app_context():
            create_archer("Alguien", "abc")
            count = db_conn.execute(
                "SELECT COUNT(*) FROM archers WHERE name = 'Alguien'"
            ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# list_archers — orden alfabético
# ---------------------------------------------------------------------------

class TestListArchers:
    def test_returns_empty_list_when_no_archers(self, app):
        with app.app_context():
            result = list_archers()
        assert result == []

    def test_returns_archers_sorted_alphabetically(self, app, db_conn):
        with app.app_context():
            create_archer("Zara Último", "1001")
            create_archer("Ana Primero", "1002")
            create_archer("Miguel Medio", "1003")
            result = list_archers()
        names = [r["name"] for r in result]
        assert names == sorted(names)

    def test_list_archers_returns_all_archers(self, app, db_conn):
        with app.app_context():
            create_archer("Arquero Uno", "2001")
            create_archer("Arquero Dos", "2002")
            create_archer("Arquero Tres", "2003")
            result = list_archers()
        assert len(result) == 3

    def test_list_archers_are_plain_dicts(self, app, db_conn):
        with app.app_context():
            create_archer("Test Archer", "3001")
            result = list_archers()
        assert isinstance(result[0], dict)

    def test_alphabetical_order_is_case_insensitive_compatible(self, app, db_conn):
        """Verifica que el orden DB (por nombre, ASC) es estable con varios registros."""
        names_to_insert = ["Beatriz", "Alejandro", "Carlos", "Diana"]
        with app.app_context():
            for i, name in enumerate(names_to_insert):
                create_archer(name, f"50{i:02d}")
            result = list_archers()
        returned_names = [r["name"] for r in result]
        assert returned_names == sorted(returned_names)


# ---------------------------------------------------------------------------
# enroll_archer — caso exitoso
# ---------------------------------------------------------------------------

class TestEnrollArcherSuccess:
    def test_enroll_in_created_tournament(self, app, db_conn, sample_tournament):
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Test", "6001")
            category_id = _insert_category(db_conn, sample_tournament["id"])
            result = enroll_archer(archer_id, sample_tournament["id"], category_id)
        assert "error" not in result
        assert result["archer_id"] == archer_id
        assert result["tournament_id"] == sample_tournament["id"]
        assert result["category_id"] == category_id
        assert "id" in result

    def test_enroll_in_active_tournament(self, app, db_conn):
        """Inscripción permitida también en torneo activo."""
        tournament_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (tournament_id, "Torneo Activo", "2025-07-01", "active"),
        )
        db_conn.commit()
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Activo", "6002")
            category_id = _insert_category(db_conn, tournament_id)
            result = enroll_archer(archer_id, tournament_id, category_id)
        assert "error" not in result

    def test_registration_persisted_in_db(self, app, db_conn, sample_tournament):
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Persistencia Test", "6003")
            category_id = _insert_category(db_conn, sample_tournament["id"])
            result = enroll_archer(archer_id, sample_tournament["id"], category_id)
            row = db_conn.execute(
                "SELECT * FROM registrations WHERE id = ?", (result["id"],)
            ).fetchone()
        assert row is not None

    def test_registration_id_is_uuid_v4(self, app, db_conn, sample_tournament):
        with app.app_context():
            archer_id = _insert_archer(db_conn, "UUID Test", "6004")
            category_id = _insert_category(db_conn, sample_tournament["id"])
            result = enroll_archer(archer_id, sample_tournament["id"], category_id)
        parsed = uuid.UUID(result["id"], version=4)
        assert str(parsed) == result["id"]


# ---------------------------------------------------------------------------
# enroll_archer — casos de error
# ---------------------------------------------------------------------------

class TestEnrollArcherErrors:
    def test_finished_tournament_returns_error(self, app, db_conn):
        tournament_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (tournament_id, "Torneo Finalizado", "2025-01-01", "finished"),
        )
        db_conn.commit()
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Error", "7001")
            category_id = _insert_category(db_conn, tournament_id)
            result = enroll_archer(archer_id, tournament_id, category_id)
        assert "error" in result
        assert "finalizado" in result["error"].lower()

    def test_nonexistent_tournament_returns_error(self, app, db_conn):
        fake_tournament_id = str(uuid.uuid4())
        fake_category_id = str(uuid.uuid4())
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Sin Torneo", "7002")
            result = enroll_archer(archer_id, fake_tournament_id, fake_category_id)
        assert "error" in result
        assert "torneo" in result["error"].lower()

    def test_nonexistent_archer_returns_error(self, app, db_conn, sample_tournament):
        fake_archer_id = str(uuid.uuid4())
        with app.app_context():
            category_id = _insert_category(db_conn, sample_tournament["id"])
            result = enroll_archer(fake_archer_id, sample_tournament["id"], category_id)
        assert "error" in result
        assert "arquero" in result["error"].lower()

    def test_category_not_belonging_to_tournament_returns_error(self, app, db_conn, sample_tournament):
        """Una categoría de otro torneo no debe ser válida para la inscripción."""
        other_tournament_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (other_tournament_id, "Otro Torneo", "2025-08-01", "created"),
        )
        db_conn.commit()
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Categoría", "7003")
            # Crear categoría en el otro torneo, no en sample_tournament
            other_category_id = _insert_category(db_conn, other_tournament_id, "Compuesto")
            result = enroll_archer(archer_id, sample_tournament["id"], other_category_id)
        assert "error" in result
        assert "categoría" in result["error"].lower() or "categoria" in result["error"].lower()

    def test_duplicate_registration_returns_error(self, app, db_conn, sample_tournament):
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Duplicado", "7004")
            category_id = _insert_category(db_conn, sample_tournament["id"])
            enroll_archer(archer_id, sample_tournament["id"], category_id)
            result = enroll_archer(archer_id, sample_tournament["id"], category_id)
        assert "error" in result
        assert "registrado" in result["error"].lower()

    def test_duplicate_registration_does_not_create_second_record(self, app, db_conn, sample_tournament):
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Conteo", "7005")
            category_id = _insert_category(db_conn, sample_tournament["id"])
            enroll_archer(archer_id, sample_tournament["id"], category_id)
            enroll_archer(archer_id, sample_tournament["id"], category_id)
            count = db_conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE archer_id = ? AND category_id = ?",
                (archer_id, category_id),
            ).fetchone()[0]
        assert count == 1

    def test_finished_tournament_does_not_create_registration(self, app, db_conn):
        tournament_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (tournament_id, "Torneo Fin Conteo", "2025-02-01", "finished"),
        )
        db_conn.commit()
        with app.app_context():
            archer_id = _insert_archer(db_conn, "Arquero Fin", "7006")
            category_id = _insert_category(db_conn, tournament_id)
            enroll_archer(archer_id, tournament_id, category_id)
            count = db_conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE archer_id = ?",
                (archer_id,),
            ).fetchone()[0]
        assert count == 0
