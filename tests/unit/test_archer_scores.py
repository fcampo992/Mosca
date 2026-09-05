"""
Tests unitarios para las funciones de puntuación del Archer_Module.

Cubre:
  - save_arrow: mapeo correcto arrow_val → points para todos los valores válidos
  - save_arrow: error con arrow_val inválido (sin registro en DB)
  - save_arrow: error cuando el torneo no está activo (finished / created)
  - get_end_summary: lista de flechas y subtotal correctos
  - get_accumulated_points: suma total correcta; 0 cuando no hay flechas

Requerimientos: 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

import uuid

import pytest

from archer.modules.archer import (
    ARROW_POINTS,
    get_accumulated_points,
    get_end_summary,
    save_arrow,
)


# ---------------------------------------------------------------------------
# Fixtures de apoyo
# ---------------------------------------------------------------------------


@pytest.fixture
def archer_in_db(db_conn):
    """Inserta un arquero directamente en la DB y retorna su dict."""
    archer_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, "1234", "Arquero Test"),
    )
    db_conn.commit()
    return {"id": archer_id, "pin": "1234", "name": "Arquero Test"}


@pytest.fixture
def active_tournament(db_conn):
    """Inserta un torneo activo y retorna su dict."""
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "Torneo Activo", "2025-07-01", "active"),
    )
    db_conn.commit()
    return {"id": t_id, "name": "Torneo Activo", "date": "2025-07-01", "status": "active"}


@pytest.fixture
def finished_tournament(db_conn):
    """Inserta un torneo finalizado y retorna su dict."""
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "Torneo Finalizado", "2025-06-01", "finished"),
    )
    db_conn.commit()
    return {"id": t_id, "status": "finished"}


@pytest.fixture
def created_tournament(db_conn):
    """Inserta un torneo en estado 'created' y retorna su dict."""
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "Torneo Creado", "2025-08-01", "created"),
    )
    db_conn.commit()
    return {"id": t_id, "status": "created"}


@pytest.fixture
def registration(db_conn, archer_in_db, active_tournament):
    """Inserta una categoría y una inscripción para el arquero en el torneo activo."""
    cat_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) VALUES (?, ?, ?, ?, ?)",
        (cat_id, active_tournament["id"], "Recurvo", "70m", "Masculino"),
    )
    reg_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO registrations (id, tournament_id, archer_id, category_id) VALUES (?, ?, ?, ?)",
        (reg_id, active_tournament["id"], archer_in_db["id"], cat_id),
    )
    db_conn.commit()
    return {"category_id": cat_id, "registration_id": reg_id}


# ---------------------------------------------------------------------------
# Tests: save_arrow — mapeo correcto arrow_val → points
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arrow_val,expected_points",
    [
        ("X", 10),
        ("10", 10),
        ("9", 9),
        ("8", 8),
        ("7", 7),
        ("6", 6),
        ("5", 5),
        ("4", 4),
        ("3", 3),
        ("2", 2),
        ("1", 1),
        ("M", 0),
    ],
)
def test_save_arrow_valid_values(
    app, db_conn, archer_in_db, active_tournament, registration, arrow_val, expected_points
):
    """save_arrow persiste el registro con los puntos correctos para cada valor válido."""
    with app.app_context():
        result = save_arrow(
            archer_id=archer_in_db["id"],
            tournament_id=active_tournament["id"],
            round_number=1,
            end_number=1,
            arrow_val=arrow_val,
        )

    assert "error" not in result, f"Error inesperado para arrow_val={arrow_val!r}: {result}"
    assert result["arrow_val"] == arrow_val
    assert result["points"] == expected_points
    assert result["archer_id"] == archer_in_db["id"]
    assert result["tournament_id"] == active_tournament["id"]

    # Verificar persistencia real en la DB
    row = db_conn.execute(
        "SELECT arrow_val, points FROM scores WHERE id = ?", (result["id"],)
    ).fetchone()
    assert row is not None
    assert row["arrow_val"] == arrow_val
    assert row["points"] == expected_points


# ---------------------------------------------------------------------------
# Tests: save_arrow — arrow_val inválido
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("invalid_val", ["", "x", "11", "0", "Y", "miss", "10.0", None])
def test_save_arrow_invalid_arrow_val_returns_error(
    app, db_conn, archer_in_db, active_tournament, invalid_val
):
    """save_arrow retorna error para valores fuera del mapeo, sin crear registro."""
    with app.app_context():
        count_before = db_conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        result = save_arrow(
            archer_id=archer_in_db["id"],
            tournament_id=active_tournament["id"],
            round_number=1,
            end_number=1,
            arrow_val=invalid_val,
        )
        count_after = db_conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]

    assert "error" in result
    assert result.get("field") == "arrow_val"
    assert count_after == count_before


# ---------------------------------------------------------------------------
# Tests: save_arrow — torneo no activo
# ---------------------------------------------------------------------------


def test_save_arrow_finished_tournament_returns_error(
    app, db_conn, archer_in_db, finished_tournament
):
    """save_arrow retorna error si el torneo está finalizado."""
    with app.app_context():
        result = save_arrow(
            archer_id=archer_in_db["id"],
            tournament_id=finished_tournament["id"],
            round_number=1,
            end_number=1,
            arrow_val="9",
        )
    assert "error" in result
    assert "activo" in result["error"].lower()


def test_save_arrow_created_tournament_returns_error(
    app, db_conn, archer_in_db, created_tournament
):
    """save_arrow retorna error si el torneo está en estado 'created'."""
    with app.app_context():
        result = save_arrow(
            archer_id=archer_in_db["id"],
            tournament_id=created_tournament["id"],
            round_number=1,
            end_number=1,
            arrow_val="7",
        )
    assert "error" in result
    assert "activo" in result["error"].lower()


def test_save_arrow_nonexistent_tournament_returns_error(
    app, db_conn, archer_in_db
):
    """save_arrow retorna error si el tournament_id no existe."""
    with app.app_context():
        result = save_arrow(
            archer_id=archer_in_db["id"],
            tournament_id=str(uuid.uuid4()),
            round_number=1,
            end_number=1,
            arrow_val="X",
        )
    assert "error" in result


# ---------------------------------------------------------------------------
# Tests: get_end_summary
# ---------------------------------------------------------------------------


def test_get_end_summary_correct_arrows_and_subtotal(
    app, db_conn, archer_in_db, active_tournament, registration
):
    """get_end_summary retorna las flechas de la tanda y el subtotal correcto."""
    archer_id = archer_in_db["id"]
    t_id = active_tournament["id"]

    with app.app_context():
        save_arrow(archer_id, t_id, 1, 1, "X")    # 10
        save_arrow(archer_id, t_id, 1, 1, "9")    # 9
        save_arrow(archer_id, t_id, 1, 1, "M")    # 0

        summary = get_end_summary(archer_id, t_id, 1, 1)

    assert len(summary["arrows"]) == 3
    assert summary["subtotal"] == 19
    # Cada elemento tiene los campos esperados
    for arrow in summary["arrows"]:
        assert "arrow_val" in arrow
        assert "points" in arrow
    # Valores en orden
    vals = [a["arrow_val"] for a in summary["arrows"]]
    assert vals == ["X", "9", "M"]


def test_get_end_summary_empty_end(app, db_conn, archer_in_db, active_tournament):
    """get_end_summary retorna lista vacía y subtotal 0 cuando no hay flechas."""
    with app.app_context():
        summary = get_end_summary(
            archer_in_db["id"], active_tournament["id"], 99, 99
        )
    assert summary["arrows"] == []
    assert summary["subtotal"] == 0


def test_get_end_summary_only_current_end(
    app, db_conn, archer_in_db, active_tournament, registration
):
    """get_end_summary solo incluye flechas de la tanda pedida, no de otras."""
    archer_id = archer_in_db["id"]
    t_id = active_tournament["id"]

    with app.app_context():
        save_arrow(archer_id, t_id, 1, 1, "8")   # tanda 1
        save_arrow(archer_id, t_id, 1, 2, "X")   # tanda 2 — no debe aparecer
        summary = get_end_summary(archer_id, t_id, 1, 1)

    assert len(summary["arrows"]) == 1
    assert summary["arrows"][0]["arrow_val"] == "8"


# ---------------------------------------------------------------------------
# Tests: get_accumulated_points
# ---------------------------------------------------------------------------


def test_get_accumulated_points_no_arrows_returns_zero(
    app, db_conn, archer_in_db, active_tournament
):
    """get_accumulated_points retorna 0 cuando el arquero no tiene flechas."""
    with app.app_context():
        total = get_accumulated_points(archer_in_db["id"], active_tournament["id"])
    assert total == 0


def test_get_accumulated_points_multiple_arrows(
    app, db_conn, archer_in_db, active_tournament, registration
):
    """get_accumulated_points retorna la suma correcta de múltiples flechas."""
    archer_id = archer_in_db["id"]
    t_id = active_tournament["id"]

    arrows = ["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"]
    expected_total = sum(ARROW_POINTS[v] for v in arrows)  # 65

    with app.app_context():
        for i, val in enumerate(arrows):
            save_arrow(archer_id, t_id, 1, 1, val)
        total = get_accumulated_points(archer_id, t_id)

    assert total == expected_total


def test_get_accumulated_points_across_multiple_ends_and_rounds(
    app, db_conn, archer_in_db, active_tournament, registration
):
    """get_accumulated_points suma todas las flechas de todas las rondas y tandas."""
    archer_id = archer_in_db["id"]
    t_id = active_tournament["id"]

    with app.app_context():
        save_arrow(archer_id, t_id, 1, 1, "X")   # 10
        save_arrow(archer_id, t_id, 1, 2, "9")   # 9
        save_arrow(archer_id, t_id, 2, 1, "8")   # 8
        save_arrow(archer_id, t_id, 2, 2, "M")   # 0
        total = get_accumulated_points(archer_id, t_id)

    assert total == 27


def test_get_accumulated_points_isolation_between_archers(
    app, db_conn, active_tournament, registration
):
    """get_accumulated_points solo cuenta puntos del arquero indicado."""
    t_id = active_tournament["id"]

    # Crear un segundo arquero
    archer2_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer2_id, "9999", "Otro Arquero"),
    )
    db_conn.commit()

    # archer_in_db fixture provee el primer arquero vía registration
    # Necesitamos el archer_id del primero desde la fixture
    archer1_id = db_conn.execute(
        "SELECT archer_id FROM registrations WHERE tournament_id = ?", (t_id,)
    ).fetchone()["archer_id"]

    with app.app_context():
        save_arrow(archer1_id, t_id, 1, 1, "X")   # 10 para archer1
        save_arrow(archer2_id, t_id, 1, 1, "9")   # 9 para archer2

        total1 = get_accumulated_points(archer1_id, t_id)
        total2 = get_accumulated_points(archer2_id, t_id)

    assert total1 == 10
    assert total2 == 9
