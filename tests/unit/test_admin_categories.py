"""
Tests unitarios para las funciones de categorías del Admin_Module.

Cubre Requerimientos 2.3, 2.4 y 2.5:
  - create_category(): existencia del torneo, unicidad, persistencia, retorno.
  - list_categories(): lista correcta por tournament_id.
"""

import uuid

import pytest

from archer.modules.admin import create_category, list_categories


# ---------------------------------------------------------------------------
# create_category — Req 2.4: torneo no encontrado
# ---------------------------------------------------------------------------

class TestCreateCategoryTournamentNotFound:
    def test_returns_error_when_tournament_does_not_exist(self, app):
        with app.app_context():
            result = create_category(
                tournament_id=str(uuid.uuid4()),
                bow_type="Recurvo",
                distance="70m",
                gender="Masculino",
            )
        assert "error" in result
        assert result["error"] == "Torneo no encontrado"

    def test_does_not_insert_category_when_tournament_missing(self, app, db_conn):
        fake_tid = str(uuid.uuid4())
        with app.app_context():
            create_category(fake_tid, "Compuesto", "50m", "Femenino")

        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM categories WHERE tournament_id = ?", (fake_tid,)
        )
        assert cursor.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# create_category — Req 2.3: persistencia exitosa
# ---------------------------------------------------------------------------

class TestCreateCategorySuccess:
    def test_returns_dict_with_correct_attributes(self, app, sample_tournament):
        with app.app_context():
            result = create_category(
                tournament_id=sample_tournament["id"],
                bow_type="Recurvo",
                distance="70m",
                gender="Masculino",
            )

        assert "error" not in result
        assert result["tournament_id"] == sample_tournament["id"]
        assert result["bow_type"] == "Recurvo"
        assert result["distance"] == "70m"
        assert result["gender"] == "Masculino"

    def test_returned_id_is_valid_uuid_v4(self, app, sample_tournament):
        with app.app_context():
            result = create_category(
                tournament_id=sample_tournament["id"],
                bow_type="Raso",
                distance="18m",
                gender="Mixto",
            )

        parsed = uuid.UUID(result["id"])
        assert parsed.version == 4

    def test_category_is_persisted_in_db(self, app, sample_tournament, db_conn):
        with app.app_context():
            result = create_category(
                tournament_id=sample_tournament["id"],
                bow_type="Compuesto",
                distance="50m",
                gender="Femenino",
            )

        cursor = db_conn.execute(
            "SELECT id, bow_type, distance, gender FROM categories WHERE id = ?",
            (result["id"],),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "Compuesto"
        assert row[2] == "50m"
        assert row[3] == "Femenino"

    def test_multiple_different_categories_can_be_created(self, app, sample_tournament, db_conn):
        combos = [
            ("Recurvo", "70m", "Masculino"),
            ("Recurvo", "70m", "Femenino"),
            ("Compuesto", "50m", "Mixto"),
        ]
        with app.app_context():
            for bow_type, distance, gender in combos:
                result = create_category(sample_tournament["id"], bow_type, distance, gender)
                assert "error" not in result

        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM categories WHERE tournament_id = ?",
            (sample_tournament["id"],),
        )
        assert cursor.fetchone()[0] == 3


# ---------------------------------------------------------------------------
# create_category — Req 2.5: unicidad de combinación
# ---------------------------------------------------------------------------

class TestCreateCategoryUniqueness:
    def test_returns_error_on_duplicate_combination(self, app, sample_tournament):
        with app.app_context():
            create_category(sample_tournament["id"], "Recurvo", "70m", "Masculino")
            result = create_category(sample_tournament["id"], "Recurvo", "70m", "Masculino")

        assert "error" in result
        assert result["error"] == "La categoría ya existe para este torneo"

    def test_duplicate_does_not_increment_count(self, app, sample_tournament, db_conn):
        with app.app_context():
            create_category(sample_tournament["id"], "Recurvo", "70m", "Masculino")
            create_category(sample_tournament["id"], "Recurvo", "70m", "Masculino")

        cursor = db_conn.execute(
            """
            SELECT COUNT(*) FROM categories
            WHERE tournament_id = ? AND bow_type = ? AND distance = ? AND gender = ?
            """,
            (sample_tournament["id"], "Recurvo", "70m", "Masculino"),
        )
        assert cursor.fetchone()[0] == 1

    def test_same_combination_in_different_tournaments_is_allowed(self, app, db_conn):
        """Dos torneos distintos pueden tener la misma combinación bow/distance/gender."""
        t1_id = str(uuid.uuid4())
        t2_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (t1_id, "Torneo A", "2025-01-01", "created"),
        )
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (t2_id, "Torneo B", "2025-02-01", "created"),
        )
        db_conn.commit()

        with app.app_context():
            r1 = create_category(t1_id, "Recurvo", "70m", "Masculino")
            r2 = create_category(t2_id, "Recurvo", "70m", "Masculino")

        assert "error" not in r1
        assert "error" not in r2
        assert r1["id"] != r2["id"]


# ---------------------------------------------------------------------------
# list_categories — Req 2.3
# ---------------------------------------------------------------------------

class TestListCategories:
    def test_returns_empty_list_when_no_categories(self, app, sample_tournament):
        with app.app_context():
            result = list_categories(sample_tournament["id"])
        assert result == []

    def test_returns_all_categories_for_tournament(self, app, sample_tournament):
        with app.app_context():
            create_category(sample_tournament["id"], "Recurvo", "70m", "Masculino")
            create_category(sample_tournament["id"], "Compuesto", "50m", "Femenino")
            result = list_categories(sample_tournament["id"])

        assert len(result) == 2

    def test_returns_plain_dicts(self, app, sample_tournament):
        with app.app_context():
            create_category(sample_tournament["id"], "Raso", "18m", "Mixto")
            result = list_categories(sample_tournament["id"])

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "id" in item
            assert "tournament_id" in item
            assert "bow_type" in item
            assert "distance" in item
            assert "gender" in item

    def test_does_not_return_categories_of_other_tournaments(self, app, db_conn):
        t1_id = str(uuid.uuid4())
        t2_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (t1_id, "Torneo X", "2025-03-01", "created"),
        )
        db_conn.execute(
            "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
            (t2_id, "Torneo Y", "2025-04-01", "created"),
        )
        db_conn.commit()

        with app.app_context():
            create_category(t1_id, "Recurvo", "70m", "Masculino")
            create_category(t2_id, "Compuesto", "50m", "Femenino")
            result_t1 = list_categories(t1_id)
            result_t2 = list_categories(t2_id)

        assert len(result_t1) == 1
        assert result_t1[0]["tournament_id"] == t1_id
        assert len(result_t2) == 1
        assert result_t2[0]["tournament_id"] == t2_id

    def test_returned_attributes_match_inserted_values(self, app, sample_tournament):
        with app.app_context():
            created = create_category(
                sample_tournament["id"], "Recurvo", "70m", "Masculino"
            )
            listed = list_categories(sample_tournament["id"])

        assert len(listed) == 1
        cat = listed[0]
        assert cat["id"] == created["id"]
        assert cat["bow_type"] == "Recurvo"
        assert cat["distance"] == "70m"
        assert cat["gender"] == "Masculino"
