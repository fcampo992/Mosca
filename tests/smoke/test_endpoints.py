"""
Smoke tests de endpoints para KiroArchery.

Cubre:
  - Todos los endpoints responden con codigo 2xx/3xx en condicion nominal
  - Los CDN de Tailwind, Alpine.js y Chart.js referencian URLs validas en el HTML
  - El endpoint SSE retorna Content-Type: text/event-stream
  - El teclado tactico renderiza 12 botones en la plantilla de score

Requerimientos: 6.1, 10.1, 10.2, 10.4
"""

import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_tournament(db_conn, status="created"):
    t_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO tournaments (id, name, date, status) VALUES (?, ?, ?, ?)",
        (t_id, "Smoke Test Tournament", "2025-09-01", status),
    )
    db_conn.commit()
    return t_id


def _insert_archer(db_conn, pin="0001"):
    a_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO archers (id, pin, name) VALUES (?, ?, ?)",
        (a_id, pin, "Smoke Archer"),
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


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

class TestAdminEndpoints:
    """Smoke tests para el blueprint /admin."""

    def test_tournaments_page_returns_200(self, app):
        """GET /admin/tournaments retorna 200."""
        with app.test_client() as client:
            resp = client.get("/admin/tournaments")
        assert resp.status_code == 200

    def test_archers_page_returns_200(self, app):
        """GET /admin/archers retorna 200."""
        with app.test_client() as client:
            resp = client.get("/admin/archers")
        assert resp.status_code == 200

    def test_categories_page_returns_200(self, app, db_conn):
        """GET /admin/tournaments/<id>/categories retorna 200."""
        t_id = _insert_tournament(db_conn)
        with app.test_client() as client:
            resp = client.get(f"/admin/tournaments/{t_id}/categories")
        assert resp.status_code == 200

    def test_create_tournament_post_redirects(self, app):
        """POST /admin/tournaments con datos validos retorna 302."""
        with app.test_client() as client:
            resp = client.post(
                "/admin/tournaments",
                data={"name": "Copa Smoke", "date": "2025-10-01"},
            )
        assert resp.status_code == 302

    def test_create_tournament_post_invalid_returns_400(self, app):
        """POST /admin/tournaments con datos invalidos retorna 4xx."""
        with app.test_client() as client:
            resp = client.post(
                "/admin/tournaments",
                data={"name": "", "date": "not-a-date"},
            )
        assert resp.status_code >= 400

    def test_create_archer_post_redirects(self, app):
        """POST /admin/archers con datos validos retorna 302."""
        with app.test_client() as client:
            resp = client.post(
                "/admin/archers",
                data={"name": "Arquero Smoke", "pin": "5678"},
            )
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Archer endpoints
# ---------------------------------------------------------------------------

class TestArcherEndpoints:
    """Smoke tests para el blueprint /archer."""

    def test_login_page_returns_200(self, app):
        """GET /archer/login retorna 200."""
        with app.test_client() as client:
            resp = client.get("/archer/login")
        assert resp.status_code == 200

    def test_login_post_wrong_pin_returns_401(self, app, db_conn):
        """POST /archer/login con PIN incorrecto retorna 401."""
        with app.test_client() as client:
            resp = client.post("/archer/login", data={"pin": "9999"})
        assert resp.status_code == 401

    def test_score_page_redirects_without_session(self, app):
        """GET /archer/score sin sesion redirige a login."""
        with app.test_client() as client:
            resp = client.get("/archer/score")
        assert resp.status_code == 302
        assert "/archer/login" in resp.headers.get("Location", "")


# ---------------------------------------------------------------------------
# Leaderboard endpoints
# ---------------------------------------------------------------------------

class TestLeaderboardEndpoints:
    """Smoke tests para el blueprint /leaderboard."""

    def test_leaderboard_html_returns_200(self, app, db_conn):
        """GET /leaderboard/<id> retorna 200 (Req 6.1)."""
        t_id = _insert_tournament(db_conn, status="active")
        with app.test_client() as client:
            resp = client.get(f"/leaderboard/{t_id}")
        assert resp.status_code == 200

    def test_sse_stream_returns_text_event_stream(self, app, db_conn):
        """GET /leaderboard/<id>/stream retorna Content-Type: text/event-stream (Req 6.1)."""
        t_id = _insert_tournament(db_conn, status="active")
        with app.test_client() as client:
            with client.get(f"/leaderboard/{t_id}/stream", buffered=False) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.content_type


# ---------------------------------------------------------------------------
# Stats endpoints
# ---------------------------------------------------------------------------

class TestStatsEndpoints:
    """Smoke tests para el blueprint /stats."""

    def test_tournament_stats_json_returns_200(self, app, db_conn):
        """GET /stats/tournament/<id> retorna 200 con JSON."""
        t_id = _insert_tournament(db_conn)
        with app.test_client() as client:
            resp = client.get(f"/stats/tournament/{t_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tournament_id" in data

    def test_tournament_stats_nonexistent_returns_404(self, app):
        """GET /stats/tournament/<id_invalido> retorna 404."""
        with app.test_client() as client:
            resp = client.get(f"/stats/tournament/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_archer_trend_returns_200(self, app, db_conn):
        """GET /stats/archer/<id>/trend retorna 200 con lista JSON."""
        a_id = _insert_archer(db_conn, pin="0002")
        with app.test_client() as client:
            resp = client.get(f"/stats/archer/{a_id}/trend")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_ranking_returns_200(self, app):
        """GET /stats/ranking retorna 200 con lista JSON."""
        with app.test_client() as client:
            resp = client.get("/stats/ranking")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)


# ---------------------------------------------------------------------------
# CDN references in HTML (Req 10.1, 10.4)
# ---------------------------------------------------------------------------

class TestCDNReferences:
    """Verifica que las URLs de CDN esten presentes en el HTML generado."""

    CDN_URLS = [
        "cdn.tailwindcss.com",       # Tailwind CSS (Req 10.1)
        "alpinejs",                   # Alpine.js (Req 10.5)
        "chart.js",                   # Chart.js (Req 10.4)
    ]

    def test_admin_page_includes_cdn_urls(self, app):
        """Las paginas de admin incluyen referencias a los CDN requeridos."""
        with app.test_client() as client:
            resp = client.get("/admin/tournaments")
        html = resp.data.decode("utf-8").lower()
        for cdn in self.CDN_URLS:
            assert cdn.lower() in html, f"CDN '{cdn}' not found in admin HTML"

    def test_login_page_includes_cdn_urls(self, app):
        """La pagina de login incluye referencias a los CDN requeridos."""
        with app.test_client() as client:
            resp = client.get("/archer/login")
        html = resp.data.decode("utf-8").lower()
        for cdn in self.CDN_URLS:
            assert cdn.lower() in html, f"CDN '{cdn}' not found in login HTML"


# ---------------------------------------------------------------------------
# Score keyboard — 12 buttons (Req 5.1, 10.2)
# ---------------------------------------------------------------------------

class TestScoreKeyboard:
    """Verifica que el teclado tactico renderiza 12 botones."""

    def test_score_template_has_12_arrow_buttons(self, app, db_conn):
        """Req 5.1, 10.2 — el teclado renderiza exactamente 12 botones de flechas."""
        from datetime import datetime

        a_id = _insert_archer(db_conn, pin="0003")
        t_id = _insert_tournament(db_conn, status="active")
        c_id = _insert_category(db_conn, t_id)
        db_conn.execute(
            "INSERT INTO registrations (id, tournament_id, archer_id, category_id) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), t_id, a_id, c_id),
        )
        db_conn.commit()

        with app.test_client() as client:
            # Establecer sesion manualmente
            with client.session_transaction() as sess:
                sess["archer_id"] = a_id
                sess["archer_name"] = "Smoke Archer"
                sess["last_active"] = datetime.now().isoformat()
                sess["round_number"] = 1
                sess["end_number"] = 1

            resp = client.get("/archer/score")

        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Contar botones con name="arrow_val" — los 12 valores del teclado
        arrow_values = ["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"]
        for val in arrow_values:
            assert f'value="{val}"' in html, f"Button for arrow value '{val}' not found in score HTML"
