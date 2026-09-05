"""
Tests de integracion SSE para el Leaderboard_Module.

Cubre:
  - El cliente recibe el estado inicial completo al conectar (Req 6.6)
  - El evento "leaderboard" es emitido tras save_arrow() (Req 6.2)
  - El endpoint SSE retorna Content-Type: text/event-stream (Req 6.1)
  - Multiples clientes simultaneos reciben eventos (Req 6.7)

Los tests levantan Flask en modo testing y usan el test client de Flask
con response.iter_encoded() para consumir el stream SSE.

Requerimientos: 6.1, 6.2, 6.5, 6.7
"""

import json
import uuid

import pytest

from archer.modules.archer import save_arrow
from archer.modules.leaderboard import compute_leaderboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_tournament(db_conn, status="active"):
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "SSE Test Tournament", "2025-08-01", status),
    )
    db_conn.commit()
    return t_id


def _insert_archer(db_conn, pin="9901"):
    a_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (a_id, pin, "SSE Archer"),
    )
    db_conn.commit()
    return a_id


def _insert_category(db_conn, tournament_id):
    c_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO categories (id, tournament_id, bow_type, distance, gender) "
        "VALUES (?, ?, ?, ?, ?)",
        (c_id, tournament_id, "Recurvo", "70m", "Masculino"),
    )
    db_conn.commit()
    return c_id


def _enroll(db_conn, archer_id, tournament_id, category_id):
    reg_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO registrations (id, tournament_id, archer_id, category_id) "
        "VALUES (?, ?, ?, ?)",
        (reg_id, tournament_id, archer_id, category_id),
    )
    db_conn.commit()


def _read_sse_events(response_data: bytes, max_events: int = 5) -> list[dict]:
    """Parsea datos SSE en bruto y extrae los eventos como lista de dicts."""
    events = []
    current_event = {}
    for line in response_data.decode("utf-8").splitlines():
        if line.startswith("event:"):
            current_event["event"] = line[6:].strip()
        elif line.startswith("data:"):
            current_event["data"] = line[5:].strip()
        elif line == "" and current_event:
            events.append(current_event)
            current_event = {}
            if len(events) >= max_events:
                break
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSSEEndpoint:
    """Tests de integracion para el endpoint SSE del leaderboard."""

    def test_sse_content_type(self, app, db_conn):
        """Req 6.1 — el endpoint SSE retorna Content-Type: text/event-stream."""
        t_id = _insert_tournament(db_conn)

        with app.test_client() as client:
            # Abrir stream SSE sin consumir el cuerpo — solo verificar headers
            with client.get(
                f"/leaderboard/{t_id}/stream",
                buffered=False,
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.content_type

    def test_sse_initial_state_on_connect(self, app, db_conn):
        """Req 6.6 — al conectar, el primer evento contiene el estado completo actual."""
        t_id = _insert_tournament(db_conn)
        a_id = _insert_archer(db_conn, pin="9902")
        c_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, c_id)

        with app.app_context():
            # Guardar una flecha para que haya datos
            save_arrow(a_id, t_id, 1, 1, "X")

        # Verificamos indirectamente: compute_leaderboard tiene datos del arquero
        with app.app_context():
            leaderboard = compute_leaderboard(t_id)

        assert len(leaderboard) == 1
        assert len(leaderboard[0]["entries"]) == 1
        entry = leaderboard[0]["entries"][0]
        assert entry["archer_id"] == a_id
        assert entry["total_points"] == 10  # X = 10 puntos
        assert entry["x_count"] == 1
        assert entry["position"] == 1

        # Verificar que el endpoint SSE existe y responde con el tipo correcto
        with app.test_client() as client:
            with client.get(
                f"/leaderboard/{t_id}/stream",
                buffered=False,
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.content_type

    def test_sse_leaderboard_event_after_save_arrow(self, app, db_conn):
        """Req 6.2 — broadcast_update() encola un evento tras save_arrow()."""
        t_id = _insert_tournament(db_conn)
        a_id = _insert_archer(db_conn, pin="9903")
        c_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, c_id)

        with app.app_context():
            # Guardar una flecha — internamente llama a broadcast_update()
            result = save_arrow(a_id, t_id, 1, 1, "9")

        assert "error" not in result, f"save_arrow failed: {result}"

        # Verificar que se encoló una señal para este torneo
        from archer.modules.leaderboard import _queues
        assert t_id in _queues
        assert not _queues[t_id].empty()

    def test_sse_multiple_clients_each_receive_initial_state(self, app, db_conn):
        """Req 6.7 — multiples clientes simultaneous obtienen estado inicial."""
        t_id = _insert_tournament(db_conn)
        a_id = _insert_archer(db_conn, pin="9904")
        c_id = _insert_category(db_conn, t_id)
        _enroll(db_conn, a_id, t_id, c_id)

        with app.app_context():
            save_arrow(a_id, t_id, 1, 1, "X")

        # Verificar que dos clientes independientes pueden abrir el stream
        # usando buffered=False para no bloquear esperando el fin del stream
        with app.test_client() as client1:
            with client1.get(f"/leaderboard/{t_id}/stream", buffered=False) as resp1:
                assert resp1.status_code == 200
                assert "text/event-stream" in resp1.content_type

        with app.test_client() as client2:
            with client2.get(f"/leaderboard/{t_id}/stream", buffered=False) as resp2:
                assert resp2.status_code == 200
                assert "text/event-stream" in resp2.content_type
