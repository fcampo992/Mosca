"""
Tests unitarios para Stats_Module — tournament_stats().

Cubre:
  - Torneo inexistente → error 404
  - avg_points_per_arrow calculado correctamente
  - top_zone_percentage calculado correctamente
  - Rondas ordenadas ASC por round_number
  - Arquero con 0 flechas → métricas 0.00 y rounds=[]
  - Filtro por archer_id → solo devuelve datos de ese arquero
  - Múltiples arqueros → devuelve a todos

Requerimientos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

import uuid

import pytest

from archer.modules.stats import tournament_stats


# ---------------------------------------------------------------------------
# Fixtures de apoyo
# ---------------------------------------------------------------------------


def _insert_archer(db_conn, name: str, pin: str) -> str:
    """Helper: inserta un arquero y retorna su id."""
    archer_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (archer_id, pin, name),
    )
    db_conn.commit()
    return archer_id


def _insert_tournament(db_conn, status: str = "active") -> str:
    """Helper: inserta un torneo con el estado indicado y retorna su id."""
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "Torneo Stats Test", "2025-08-01", status),
    )
    db_conn.commit()
    return t_id


def _insert_category(db_conn, tournament_id: str) -> str:
    """Helper: inserta una categoría para el torneo y retorna su id."""
    cat_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) "
        "VALUES (?, ?, ?, ?, ?)",
        (cat_id, tournament_id, "Recurvo", "70m", "Masculino"),
    )
    db_conn.commit()
    return cat_id


def _enroll(db_conn, archer_id: str, tournament_id: str, category_id: str) -> None:
    """Helper: inscribe un arquero en un torneo/categoría."""
    reg_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO registrations (id, tournament_id, archer_id, category_id) "
        "VALUES (?, ?, ?, ?)",
        (reg_id, tournament_id, archer_id, category_id),
    )
    db_conn.commit()


def _insert_score(
    db_conn,
    archer_id: str,
    tournament_id: str,
    round_number: int,
    end_number: int,
    arrow_val: str,
    points: int,
) -> None:
    """Helper: inserta directamente una fila en scores."""
    score_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO scores "
        "(id, tournament_id, archer_id, round_number, end_number, arrow_val, points) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (score_id, tournament_id, archer_id, round_number, end_number, arrow_val, points),
    )
    db_conn.commit()


# ---------------------------------------------------------------------------
# 1. Torneo no existente → error 404
# ---------------------------------------------------------------------------


def test_tournament_stats_nonexistent_tournament_returns_404(app):
    """tournament_stats devuelve error con status_code 404 para un ID inexistente."""
    with app.app_context():
        result = tournament_stats(str(uuid.uuid4()))

    assert result.get("status_code") == 404
    assert "error" in result
    assert "no encontrado" in result["error"].lower()


# ---------------------------------------------------------------------------
# 2. avg_points_per_arrow calculado correctamente
# ---------------------------------------------------------------------------


def test_tournament_stats_avg_points_per_arrow(app, db_conn):
    """avg_points_per_arrow es round(sum(points)/count, 2)."""
    t_id = _insert_tournament(db_conn)
    a_id = _insert_archer(db_conn, "Ana", "1111")
    cat_id = _insert_category(db_conn, t_id)
    _enroll(db_conn, a_id, t_id, cat_id)

    # Flechas: X=10, 9=9, 8=8, M=0  → sum=27, count=4, avg=6.75
    for arrow_val, points in [("X", 10), ("9", 9), ("8", 8), ("M", 0)]:
        _insert_score(db_conn, a_id, t_id, 1, 1, arrow_val, points)

    with app.app_context():
        result = tournament_stats(t_id)

    assert result["tournament_id"] == t_id
    archers = result["archers"]
    assert len(archers) == 1
    assert archers[0]["avg_points_per_arrow"] == round(27 / 4, 2)  # 6.75


# ---------------------------------------------------------------------------
# 3. top_zone_percentage calculado correctamente
# ---------------------------------------------------------------------------


def test_tournament_stats_top_zone_percentage(app, db_conn):
    """top_zone_percentage = round(count(X|10)/total*100, 2)."""
    t_id = _insert_tournament(db_conn)
    a_id = _insert_archer(db_conn, "Bruno", "2222")
    cat_id = _insert_category(db_conn, t_id)
    _enroll(db_conn, a_id, t_id, cat_id)

    # Flechas: X=10, 10=10, 9=9, 8=8  → top_zone=2, total=4 → 50.00%
    for arrow_val, points in [("X", 10), ("10", 10), ("9", 9), ("8", 8)]:
        _insert_score(db_conn, a_id, t_id, 1, 1, arrow_val, points)

    with app.app_context():
        result = tournament_stats(t_id)

    archer_data = result["archers"][0]
    assert archer_data["top_zone_percentage"] == round(2 / 4 * 100, 2)  # 50.00


# ---------------------------------------------------------------------------
# 4. Rondas ordenadas ASC por round_number
# ---------------------------------------------------------------------------


def test_tournament_stats_rounds_ordered_asc(app, db_conn):
    """La lista rounds está ordenada de forma ascendente por round_number."""
    t_id = _insert_tournament(db_conn)
    a_id = _insert_archer(db_conn, "Carlos", "3333")
    cat_id = _insert_category(db_conn, t_id)
    _enroll(db_conn, a_id, t_id, cat_id)

    # Insertar flechas en rondas 3, 1, 2 fuera de orden
    _insert_score(db_conn, a_id, t_id, 3, 1, "9", 9)
    _insert_score(db_conn, a_id, t_id, 1, 1, "X", 10)
    _insert_score(db_conn, a_id, t_id, 2, 1, "8", 8)

    with app.app_context():
        result = tournament_stats(t_id)

    rounds = result["archers"][0]["rounds"]
    round_numbers = [r["round_number"] for r in rounds]
    assert round_numbers == sorted(round_numbers)
    assert round_numbers == [1, 2, 3]


# ---------------------------------------------------------------------------
# 5. Arquero con 0 flechas → métricas 0.00, rounds=[]
# ---------------------------------------------------------------------------


def test_tournament_stats_archer_with_zero_arrows(app, db_conn):
    """Arquero inscrito sin flechas obtiene avg=0.00, top_zone=0.00, rounds=[]."""
    t_id = _insert_tournament(db_conn)
    a_id = _insert_archer(db_conn, "Diana", "4444")
    cat_id = _insert_category(db_conn, t_id)
    _enroll(db_conn, a_id, t_id, cat_id)

    # No se inserta ninguna flecha

    with app.app_context():
        result = tournament_stats(t_id)

    assert len(result["archers"]) == 1
    archer_data = result["archers"][0]
    assert archer_data["avg_points_per_arrow"] == 0.00
    assert archer_data["top_zone_percentage"] == 0.00
    assert archer_data["rounds"] == []


# ---------------------------------------------------------------------------
# 6. Filtro por archer_id → solo devuelve datos de ese arquero
# ---------------------------------------------------------------------------


def test_tournament_stats_archer_id_filter_isolates_data(app, db_conn):
    """Con archer_id suministrado, solo se devuelven datos de ese arquero."""
    t_id = _insert_tournament(db_conn)
    cat_id = _insert_category(db_conn, t_id)

    a1_id = _insert_archer(db_conn, "Elena", "5555")
    a2_id = _insert_archer(db_conn, "Felipe", "6666")
    _enroll(db_conn, a1_id, t_id, cat_id)
    _enroll(db_conn, a2_id, t_id, cat_id)

    _insert_score(db_conn, a1_id, t_id, 1, 1, "X", 10)
    _insert_score(db_conn, a2_id, t_id, 1, 1, "9", 9)

    with app.app_context():
        result = tournament_stats(t_id, archer_id=a1_id)

    assert len(result["archers"]) == 1
    assert result["archers"][0]["archer_id"] == a1_id
    assert result["archers"][0]["avg_points_per_arrow"] == 10.00


# ---------------------------------------------------------------------------
# 7. Múltiples arqueros → devuelve todos
# ---------------------------------------------------------------------------


def test_tournament_stats_multiple_archers_returns_all(app, db_conn):
    """Sin filtro, tournament_stats devuelve datos de todos los arqueros inscritos."""
    t_id = _insert_tournament(db_conn)
    cat_id = _insert_category(db_conn, t_id)

    archer_ids = []
    for i, (name, pin) in enumerate(
        [("Gabriel", "7001"), ("Hana", "7002"), ("Iván", "7003")]
    ):
        a_id = _insert_archer(db_conn, name, pin)
        archer_ids.append(a_id)
        _enroll(db_conn, a_id, t_id, cat_id)
        _insert_score(db_conn, a_id, t_id, 1, 1, "9", 9)

    with app.app_context():
        result = tournament_stats(t_id)

    returned_ids = {a["archer_id"] for a in result["archers"]}
    assert returned_ids == set(archer_ids)
    assert len(result["archers"]) == 3


# ===========================================================================
# Tests para archer_trend()
# Requerimientos: 8.1, 8.2, 8.3, 8.4
# ===========================================================================

from archer.modules.stats import archer_trend, global_ranking


def _insert_finished_tournament(db_conn, name: str, date: str) -> str:
    """Helper: inserta un torneo con estado 'finished' y retorna su id."""
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, name, date, "finished"),
    )
    db_conn.commit()
    return t_id


class TestArcherTrend:
    """Tests unitarios para archer_trend()."""

    def test_no_finished_tournaments_returns_empty_list(self, app, db_conn):
        """Req 8.3 — arquero sin torneos finished devuelve arreglo vacío."""
        a_id = _insert_archer(db_conn, "Zoe", "8001")
        # Solo crear un torneo 'active' (no finished)
        t_id = _insert_tournament(db_conn, status="active")
        cat_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, cat_id)

        with app.app_context():
            result = archer_trend(a_id)

        assert result == []

    def test_trend_returns_correct_avg_per_tournament(self, app, db_conn):
        """Req 8.1, 8.2 — avg_points_per_arrow calculado correctamente por torneo."""
        a_id = _insert_archer(db_conn, "Mateo", "8002")
        t_id = _insert_finished_tournament(db_conn, "Copa Verano", "2025-01-15")
        cat_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, cat_id)

        # X=10, 10=10, 8=8 → sum=28, count=3 → avg=9.33
        for arrow_val, points in [("X", 10), ("10", 10), ("8", 8)]:
            _insert_score(db_conn, a_id, t_id, 1, 1, arrow_val, points)

        with app.app_context():
            result = archer_trend(a_id)

        assert len(result) == 1
        assert result[0]["tournament_name"] == "Copa Verano"
        assert result[0]["date"] == "2025-01-15"
        assert result[0]["avg_points_per_arrow"] == round(28 / 3, 2)

    def test_trend_zero_arrows_in_finished_tournament(self, app, db_conn):
        """Req 8.4 — torneo finished sin flechas aparece con avg=0.00."""
        a_id = _insert_archer(db_conn, "Lucia", "8003")
        t_id = _insert_finished_tournament(db_conn, "Copa Invierno", "2025-03-10")
        cat_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, cat_id)
        # No se insertan flechas

        with app.app_context():
            result = archer_trend(a_id)

        assert len(result) == 1
        assert result[0]["avg_points_per_arrow"] == 0.00

    def test_trend_ordered_asc_by_date(self, app, db_conn):
        """Req 8.1 — resultados ordenados ASC por fecha del torneo."""
        a_id = _insert_archer(db_conn, "Pedro", "8004")
        cat_id = None

        # Insertar torneos en orden inverso de fecha
        for name, date in [
            ("Copa C", "2025-09-01"),
            ("Copa A", "2025-01-01"),
            ("Copa B", "2025-05-01"),
        ]:
            t_id = _insert_finished_tournament(db_conn, name, date)
            c_id = _insert_category(db_conn, t_id)
            _enroll(db_conn, a_id, t_id, c_id)
            _insert_score(db_conn, a_id, t_id, 1, 1, "9", 9)

        with app.app_context():
            result = archer_trend(a_id)

        dates = [r["date"] for r in result]
        assert dates == sorted(dates)
        assert [r["tournament_name"] for r in result] == ["Copa A", "Copa B", "Copa C"]

    def test_trend_response_fields_present(self, app, db_conn):
        """Req 8.2 — cada objeto tiene tournament_name, date, avg_points_per_arrow."""
        a_id = _insert_archer(db_conn, "Sara", "8005")
        t_id = _insert_finished_tournament(db_conn, "Copa Otoño", "2025-11-20")
        cat_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, cat_id)
        _insert_score(db_conn, a_id, t_id, 1, 1, "9", 9)

        with app.app_context():
            result = archer_trend(a_id)

        assert len(result) == 1
        obj = result[0]
        assert set(obj.keys()) == {"tournament_name", "date", "avg_points_per_arrow"}

    def test_trend_excludes_non_finished_tournaments(self, app, db_conn):
        """Req 8.1 — solo torneos 'finished' aparecen en la tendencia."""
        a_id = _insert_archer(db_conn, "Tomás", "8006")

        # Un torneo finished
        t_fin = _insert_finished_tournament(db_conn, "Finalizado", "2025-04-01")
        cat_fin = _insert_category(db_conn, t_fin)
        _enroll(db_conn, a_id, t_fin, cat_fin)
        _insert_score(db_conn, a_id, t_fin, 1, 1, "9", 9)

        # Un torneo active — no debe aparecer
        t_act = _insert_tournament(db_conn, status="active")
        cat_act = _insert_category(db_conn, t_act)
        _enroll(db_conn, a_id, t_act, cat_act)
        _insert_score(db_conn, a_id, t_act, 1, 1, "X", 10)

        with app.app_context():
            result = archer_trend(a_id)

        assert len(result) == 1
        assert result[0]["tournament_name"] == "Finalizado"


# ===========================================================================
# Tests para global_ranking()
# Requerimientos: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
# ===========================================================================

class TestGlobalRanking:
    """Tests unitarios para global_ranking()."""

    def test_returns_all_archers_including_no_finished(self, app, db_conn):
        """Req 9.4 — arqueros sin torneos finished aparecen con totales en cero."""
        a_id = _insert_archer(db_conn, "Arquero Sin Torneo", "9001")

        with app.app_context():
            result = global_ranking()

        ids = [r["archer_id"] for r in result]
        assert a_id in ids
        entry = next(r for r in result if r["archer_id"] == a_id)
        assert entry["total_points"] == 0
        assert entry["avg_points_per_arrow"] == 0.00
        assert entry["tournaments_played"] == 0

    def test_total_points_sum_only_finished(self, app, db_conn):
        """Req 9.3 — solo puntos de torneos 'finished' se suman al ranking."""
        a_id = _insert_archer(db_conn, "Arquero Mixto", "9002")

        # Torneo finished con 3 flechas
        t_fin = _insert_finished_tournament(db_conn, "Fin", "2025-06-01")
        cat_fin = _insert_category(db_conn, t_fin)
        _enroll(db_conn, a_id, t_fin, cat_fin)
        for val, pts in [("X", 10), ("9", 9), ("8", 8)]:
            _insert_score(db_conn, a_id, t_fin, 1, 1, val, pts)

        # Torneo active con flechas — NO debe sumar
        t_act = _insert_tournament(db_conn, status="active")
        cat_act = _insert_category(db_conn, t_act)
        _enroll(db_conn, a_id, t_act, cat_act)
        for val, pts in [("X", 10), ("X", 10), ("X", 10)]:
            _insert_score(db_conn, a_id, t_act, 1, 1, val, pts)

        with app.app_context():
            result = global_ranking()

        entry = next(r for r in result if r["archer_id"] == a_id)
        # Solo los 27 puntos del torneo finished
        assert entry["total_points"] == 27
        assert entry["tournaments_played"] == 1

    def test_ordering_by_total_points_desc(self, app, db_conn):
        """Req 9.2 — ordenado por total_points DESC."""
        a1 = _insert_archer(db_conn, "Arquero Alto", "9003")
        a2 = _insert_archer(db_conn, "Arquero Bajo", "9004")

        for archer, points_list in [(a1, [10, 10, 10]), (a2, [1, 1, 1])]:
            t = _insert_finished_tournament(db_conn, f"T-{archer[:4]}", "2025-07-01")
            c = _insert_category(db_conn, t)
            _enroll(db_conn, archer, t, c)
            for pts in points_list:
                _insert_score(db_conn, archer, t, 1, 1, str(pts), pts)

        with app.app_context():
            result = global_ranking()

        # Filtrar solo estos dos arqueros
        entries = [r for r in result if r["archer_id"] in {a1, a2}]
        assert entries[0]["archer_id"] == a1   # 30 pts > 3 pts
        assert entries[1]["archer_id"] == a2

    def test_tie_broken_by_name_asc(self, app, db_conn):
        """Req 9.2 — empate de puntaje desempate por name ASC."""
        # Dos arqueros con el mismo puntaje
        a_z = _insert_archer(db_conn, "Zara Último", "9005")
        a_a = _insert_archer(db_conn, "Ana Primero", "9006")

        for archer in [a_z, a_a]:
            t = _insert_finished_tournament(db_conn, f"Copa-{archer[:4]}", "2025-08-01")
            c = _insert_category(db_conn, t)
            _enroll(db_conn, archer, t, c)
            _insert_score(db_conn, archer, t, 1, 1, "9", 9)

        with app.app_context():
            result = global_ranking()

        entries = [r for r in result if r["archer_id"] in {a_z, a_a}]
        # Ana debe aparecer antes que Zara (ambos con 9 puntos)
        assert entries[0]["archer_id"] == a_a
        assert entries[1]["archer_id"] == a_z

    def test_position_field_sequential(self, app, db_conn):
        """Req 9.1 — campo 'position' es secuencial desde 1."""
        for i, pin in enumerate(["9007", "9008", "9009"], start=1):
            _insert_archer(db_conn, f"Archer {i}", pin)

        with app.app_context():
            result = global_ranking()

        positions = [r["position"] for r in result]
        assert positions == list(range(1, len(result) + 1))

    def test_avg_points_per_arrow_calculation(self, app, db_conn):
        """Req 9.1 — avg_points_per_arrow = round(total_points/total_arrows, 2)."""
        a_id = _insert_archer(db_conn, "Avg Tester", "9010")
        t = _insert_finished_tournament(db_conn, "Copa Avg", "2025-09-01")
        c = _insert_category(db_conn, t)
        _enroll(db_conn, a_id, t, c)

        # X=10, 9=9, 8=8, M=0 → sum=27, count=4 → avg=6.75
        for val, pts in [("X", 10), ("9", 9), ("8", 8), ("M", 0)]:
            _insert_score(db_conn, a_id, t, 1, 1, val, pts)

        with app.app_context():
            result = global_ranking()

        entry = next(r for r in result if r["archer_id"] == a_id)
        assert entry["total_points"] == 27
        assert entry["avg_points_per_arrow"] == round(27 / 4, 2)  # 6.75

    def test_tournaments_played_counts_distinct_finished(self, app, db_conn):
        """Req 9.1 — tournaments_played es conteo de torneos finished distintos."""
        a_id = _insert_archer(db_conn, "Multi Torneo", "9011")

        for name, date in [
            ("T1", "2025-01-01"),
            ("T2", "2025-02-01"),
            ("T3", "2025-03-01"),
        ]:
            t = _insert_finished_tournament(db_conn, name, date)
            c = _insert_category(db_conn, t)
            _enroll(db_conn, a_id, t, c)
            _insert_score(db_conn, a_id, t, 1, 1, "9", 9)

        with app.app_context():
            result = global_ranking()

        entry = next(r for r in result if r["archer_id"] == a_id)
        assert entry["tournaments_played"] == 3

    def test_response_fields_present(self, app, db_conn):
        """Req 9.5 — cada entrada tiene todos los campos requeridos."""
        a_id = _insert_archer(db_conn, "Fields Tester", "9012")

        with app.app_context():
            result = global_ranking()

        entry = next(r for r in result if r["archer_id"] == a_id)
        assert set(entry.keys()) == {
            "position",
            "archer_id",
            "name",
            "photo_url",
            "total_points",
            "avg_points_per_arrow",
            "tournaments_played",
        }
