"""
Tests unitarios para el Leaderboard_Module.

Cubre:
  - compute_leaderboard: estructura correcta (categorías y entries)
  - compute_leaderboard: orden por total_points DESC, x_count DESC, ten_count DESC
  - compute_leaderboard: asignación correcta de posiciones 1-based
  - compute_leaderboard: incluye arqueros con 0 scores
  - broadcast_update: encola el item en la queue del torneo
  - sse_stream: el primer evento contiene el estado completo del leaderboard

Requerimientos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

import json
import uuid

import pytest

from archer.modules.leaderboard import broadcast_update, compute_leaderboard, sse_stream, _queues


# ---------------------------------------------------------------------------
# Fixtures de apoyo
# ---------------------------------------------------------------------------


@pytest.fixture
def active_tournament(db_conn):
    """Inserta un torneo activo y retorna su dict."""
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "Torneo Leaderboard", "2025-08-01", "active"),
    )
    db_conn.commit()
    return {"id": t_id}


@pytest.fixture
def category(db_conn, active_tournament):
    """Crea una categoría en el torneo activo y retorna su dict."""
    cat_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) VALUES (?, ?, ?, ?, ?)",
        (cat_id, active_tournament["id"], "Recurvo", "70m", "Masculino"),
    )
    db_conn.commit()
    return {"id": cat_id, "bow_type": "Recurvo", "distance": "70m", "gender": "Masculino"}


def _make_archer(db_conn, pin: str, name: str) -> dict:
    """Inserta un arquero y retorna su dict."""
    archer_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, pin, name),
    )
    db_conn.commit()
    return {"id": archer_id, "name": name}


def _enroll(db_conn, tournament_id: str, archer_id: str, category_id: str) -> str:
    """Inscribe un arquero en una categoría y retorna el registration id."""
    reg_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO registrations (id, tournament_id, archer_id, category_id) VALUES (?, ?, ?, ?)",
        (reg_id, tournament_id, archer_id, category_id),
    )
    db_conn.commit()
    return reg_id


def _add_score(db_conn, tournament_id: str, archer_id: str, arrow_val: str, points: int) -> None:
    """Inserta una flecha directamente en scores."""
    db_conn.execute(
        "INSERT INTO scores (id, tournament_id, archer_id, round_number, end_number, arrow_val, points) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), tournament_id, archer_id, 1, 1, arrow_val, points),
    )
    db_conn.commit()


# ---------------------------------------------------------------------------
# Test: estructura correcta
# ---------------------------------------------------------------------------


def test_compute_leaderboard_returns_correct_structure(app, db_conn, active_tournament, category):
    """compute_leaderboard retorna lista de categorías con los campos requeridos."""
    archer = _make_archer(db_conn, "1111", "Juan")
    _enroll(db_conn, active_tournament["id"], archer["id"], category["id"])

    with app.app_context():
        result = compute_leaderboard(active_tournament["id"])

    assert isinstance(result, list)
    assert len(result) == 1

    cat_entry = result[0]
    assert cat_entry["category_id"] == category["id"]
    assert cat_entry["bow_type"] == "Recurvo"
    assert cat_entry["distance"] == "70m"
    assert cat_entry["gender"] == "Masculino"
    assert "entries" in cat_entry

    entry = cat_entry["entries"][0]
    assert entry["archer_id"] == archer["id"]
    assert entry["name"] == "Juan"
    assert "position" in entry
    assert "total_points" in entry
    assert "x_count" in entry
    assert "ten_count" in entry


def test_compute_leaderboard_empty_category_has_empty_entries(app, db_conn, active_tournament, category):
    """compute_leaderboard incluye categorías sin arqueros con entries=[]."""
    with app.app_context():
        result = compute_leaderboard(active_tournament["id"])

    assert len(result) == 1
    assert result[0]["entries"] == []


def test_compute_leaderboard_no_categories_returns_empty_list(app, db_conn, active_tournament):
    """compute_leaderboard retorna lista vacía cuando el torneo no tiene categorías."""
    with app.app_context():
        result = compute_leaderboard(active_tournament["id"])

    assert result == []


# ---------------------------------------------------------------------------
# Test: ordenamiento correcto
# ---------------------------------------------------------------------------


def test_compute_leaderboard_sorts_by_total_points_desc(app, db_conn, active_tournament, category):
    """Ordena arqueros por total_points DESC dentro de la categoría."""
    archer_low = _make_archer(db_conn, "2001", "Archer Low")
    archer_high = _make_archer(db_conn, "2002", "Archer High")
    t_id = active_tournament["id"]
    cat_id = category["id"]

    _enroll(db_conn, t_id, archer_low["id"], cat_id)
    _enroll(db_conn, t_id, archer_high["id"], cat_id)

    # archer_low → 5 pts, archer_high → 10 pts
    _add_score(db_conn, t_id, archer_low["id"], "5", 5)
    _add_score(db_conn, t_id, archer_high["id"], "10", 10)

    with app.app_context():
        result = compute_leaderboard(t_id)

    entries = result[0]["entries"]
    assert entries[0]["archer_id"] == archer_high["id"]
    assert entries[1]["archer_id"] == archer_low["id"]


def test_compute_leaderboard_tiebreak_by_x_count_desc(app, db_conn, active_tournament, category):
    """Desempate por x_count DESC cuando total_points es igual."""
    archer_no_x = _make_archer(db_conn, "3001", "Sin X")
    archer_with_x = _make_archer(db_conn, "3002", "Con X")
    t_id = active_tournament["id"]
    cat_id = category["id"]

    _enroll(db_conn, t_id, archer_no_x["id"], cat_id)
    _enroll(db_conn, t_id, archer_with_x["id"], cat_id)

    # Ambos tienen 10 pts: uno con "10", otro con "X"
    _add_score(db_conn, t_id, archer_no_x["id"], "10", 10)
    _add_score(db_conn, t_id, archer_with_x["id"], "X", 10)

    with app.app_context():
        result = compute_leaderboard(t_id)

    entries = result[0]["entries"]
    assert entries[0]["archer_id"] == archer_with_x["id"]   # x_count=1 gana
    assert entries[1]["archer_id"] == archer_no_x["id"]


def test_compute_leaderboard_tiebreak_by_ten_count_desc(app, db_conn, active_tournament, category):
    """Desempate por ten_count DESC cuando total_points y x_count son iguales."""
    archer_no_ten = _make_archer(db_conn, "4001", "Sin 10")
    archer_with_ten = _make_archer(db_conn, "4002", "Con 10")
    t_id = active_tournament["id"]
    cat_id = category["id"]

    _enroll(db_conn, t_id, archer_no_ten["id"], cat_id)
    _enroll(db_conn, t_id, archer_with_ten["id"], cat_id)

    # Ambos con 9 pts, ninguno tiene X ni 10: archer_with_ten recibe un "10" adicional
    # Para igualar puntos totales: archer_no_ten → 9+9=18, archer_with_ten → 10+8=18
    _add_score(db_conn, t_id, archer_no_ten["id"], "9", 9)
    _add_score(db_conn, t_id, archer_no_ten["id"], "9", 9)
    _add_score(db_conn, t_id, archer_with_ten["id"], "10", 10)
    _add_score(db_conn, t_id, archer_with_ten["id"], "8", 8)

    with app.app_context():
        result = compute_leaderboard(t_id)

    entries = result[0]["entries"]
    # archer_with_ten tiene ten_count=1, archer_no_ten tiene ten_count=0
    assert entries[0]["archer_id"] == archer_with_ten["id"]
    assert entries[1]["archer_id"] == archer_no_ten["id"]


# ---------------------------------------------------------------------------
# Test: posiciones 1-based correctas
# ---------------------------------------------------------------------------


def test_compute_leaderboard_assigns_correct_positions(app, db_conn, active_tournament, category):
    """Asigna posiciones 1-based según el orden de clasificación."""
    archers = [_make_archer(db_conn, str(5000 + i), f"Archer {i}") for i in range(3)]
    t_id = active_tournament["id"]
    cat_id = category["id"]

    for archer in archers:
        _enroll(db_conn, t_id, archer["id"], cat_id)

    # Asignar puntos: archers[0]=30, archers[1]=20, archers[2]=10
    points_map = {archers[0]["id"]: 30, archers[1]["id"]: 20, archers[2]["id"]: 10}
    arrow_map = {30: ("X", 10), 20: ("9", 9), 10: ("8", 8)}

    # Insertar flechas apropiadas para alcanzar esos totales
    _add_score(db_conn, t_id, archers[0]["id"], "X", 10)
    _add_score(db_conn, t_id, archers[0]["id"], "X", 10)
    _add_score(db_conn, t_id, archers[0]["id"], "X", 10)
    _add_score(db_conn, t_id, archers[1]["id"], "9", 9)
    _add_score(db_conn, t_id, archers[1]["id"], "9", 9)
    _add_score(db_conn, t_id, archers[2]["id"], "8", 8)
    _add_score(db_conn, t_id, archers[2]["id"], "2", 2)

    with app.app_context():
        result = compute_leaderboard(t_id)

    entries = result[0]["entries"]
    assert len(entries) == 3
    assert entries[0]["position"] == 1
    assert entries[1]["position"] == 2
    assert entries[2]["position"] == 3
    # El de más puntos queda en posición 1
    assert entries[0]["total_points"] == 30


# ---------------------------------------------------------------------------
# Test: arqueros con 0 scores incluidos
# ---------------------------------------------------------------------------


def test_compute_leaderboard_includes_archers_with_zero_scores(
    app, db_conn, active_tournament, category
):
    """Arqueros inscritos sin flechas aparecen con total_points=0, x_count=0, ten_count=0."""
    archer = _make_archer(db_conn, "6001", "Sin Flechas")
    _enroll(db_conn, active_tournament["id"], archer["id"], category["id"])

    with app.app_context():
        result = compute_leaderboard(active_tournament["id"])

    entries = result[0]["entries"]
    assert len(entries) == 1
    assert entries[0]["total_points"] == 0
    assert entries[0]["x_count"] == 0
    assert entries[0]["ten_count"] == 0
    assert entries[0]["position"] == 1


def test_compute_leaderboard_mixed_zero_and_nonzero(app, db_conn, active_tournament, category):
    """Arquero con 0 flechas aparece después del que tiene puntos."""
    archer_scored = _make_archer(db_conn, "7001", "Con Puntos")
    archer_zero = _make_archer(db_conn, "7002", "Sin Puntos")
    t_id = active_tournament["id"]
    cat_id = category["id"]

    _enroll(db_conn, t_id, archer_scored["id"], cat_id)
    _enroll(db_conn, t_id, archer_zero["id"], cat_id)

    _add_score(db_conn, t_id, archer_scored["id"], "9", 9)

    with app.app_context():
        result = compute_leaderboard(t_id)

    entries = result[0]["entries"]
    assert entries[0]["archer_id"] == archer_scored["id"]
    assert entries[0]["position"] == 1
    assert entries[1]["archer_id"] == archer_zero["id"]
    assert entries[1]["position"] == 2
    assert entries[1]["total_points"] == 0


# ---------------------------------------------------------------------------
# Test: múltiples categorías
# ---------------------------------------------------------------------------


def test_compute_leaderboard_multiple_categories(app, db_conn, active_tournament):
    """compute_leaderboard retorna todas las categorías del torneo."""
    t_id = active_tournament["id"]

    cat_ids = []
    for i, bow in enumerate(["Recurvo", "Compuesto", "Raso"]):
        cat_id = str(uuid.uuid4())
        db_conn.execute(
            "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) VALUES (?, ?, ?, ?, ?)",
            (cat_id, t_id, bow, "70m", "Masculino"),
        )
        cat_ids.append(cat_id)
    db_conn.commit()

    with app.app_context():
        result = compute_leaderboard(t_id)

    assert len(result) == 3
    bow_types = {cat["bow_type"] for cat in result}
    assert bow_types == {"Recurvo", "Compuesto", "Raso"}


def test_compute_leaderboard_x_and_ten_counts_are_correct(app, db_conn, active_tournament, category):
    """x_count y ten_count se calculan correctamente."""
    archer = _make_archer(db_conn, "8001", "Tirador")
    t_id = active_tournament["id"]
    cat_id = category["id"]
    _enroll(db_conn, t_id, archer["id"], cat_id)

    _add_score(db_conn, t_id, archer["id"], "X", 10)
    _add_score(db_conn, t_id, archer["id"], "X", 10)
    _add_score(db_conn, t_id, archer["id"], "10", 10)
    _add_score(db_conn, t_id, archer["id"], "9", 9)
    _add_score(db_conn, t_id, archer["id"], "M", 0)

    with app.app_context():
        result = compute_leaderboard(t_id)

    entry = result[0]["entries"][0]
    assert entry["x_count"] == 2
    assert entry["ten_count"] == 1
    assert entry["total_points"] == 39


# ---------------------------------------------------------------------------
# Test: broadcast_update
# ---------------------------------------------------------------------------


def test_broadcast_update_puts_item_in_queue(active_tournament):
    """broadcast_update encola el tournament_id en la queue correspondiente."""
    t_id = active_tournament["id"]

    # Limpiar cualquier queue residual del torneo
    if t_id in _queues:
        del _queues[t_id]

    broadcast_update(t_id)

    assert t_id in _queues
    assert not _queues[t_id].empty()
    item = _queues[t_id].get_nowait()
    assert item == t_id


def test_broadcast_update_creates_queue_if_not_exists(active_tournament):
    """broadcast_update crea la queue si no existía para ese torneo."""
    t_id = str(uuid.uuid4())  # ID nuevo, sin queue previa

    if t_id in _queues:
        del _queues[t_id]

    broadcast_update(t_id)

    assert t_id in _queues


def test_broadcast_update_multiple_calls(active_tournament):
    """Múltiples broadcast_update encolan múltiples items."""
    t_id = active_tournament["id"]
    if t_id in _queues:
        del _queues[t_id]

    broadcast_update(t_id)
    broadcast_update(t_id)
    broadcast_update(t_id)

    assert _queues[t_id].qsize() == 3


# ---------------------------------------------------------------------------
# Test: sse_stream — primer evento contiene leaderboard completo
# ---------------------------------------------------------------------------


def test_sse_stream_first_event_is_leaderboard(app, db_conn, active_tournament, category):
    """sse_stream emite el estado completo del leaderboard como primer evento (Req 6.6)."""
    archer = _make_archer(db_conn, "9001", "Sagitario")
    t_id = active_tournament["id"]
    cat_id = category["id"]
    _enroll(db_conn, t_id, archer["id"], cat_id)
    _add_score(db_conn, t_id, archer["id"], "X", 10)
    _add_score(db_conn, t_id, archer["id"], "9", 9)

    with app.app_context():
        gen = sse_stream(t_id)
        first_event = next(gen)
        gen.close()  # Liberar el generador

    # Verificar formato SSE
    assert first_event.startswith("event: leaderboard\n")
    assert first_event.endswith("\n\n")

    # Extraer y parsear el payload JSON
    data_line = [line for line in first_event.split("\n") if line.startswith("data: ")][0]
    payload = json.loads(data_line[len("data: "):])

    assert payload["tournament_id"] == t_id
    assert "categories" in payload
    assert len(payload["categories"]) == 1

    entries = payload["categories"][0]["entries"]
    assert len(entries) == 1
    assert entries[0]["archer_id"] == archer["id"]
    assert entries[0]["total_points"] == 19
    assert entries[0]["x_count"] == 1
    assert entries[0]["ten_count"] == 0
    assert entries[0]["position"] == 1


def test_sse_stream_first_event_format(app, db_conn, active_tournament):
    """sse_stream primer evento tiene el formato SSE correcto."""
    t_id = active_tournament["id"]

    with app.app_context():
        gen = sse_stream(t_id)
        first_event = next(gen)
        gen.close()

    lines = first_event.split("\n")
    assert lines[0] == "event: leaderboard"
    assert lines[1].startswith("data: ")
    # Doble newline al final → las dos últimas líneas son vacías
    assert first_event.endswith("\n\n")
