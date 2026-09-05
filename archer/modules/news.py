"""
News_Module — gestión de noticias y alertas para la marquesina.

Expone:
  - list_news()           Retorna todas las noticias ordenadas por fecha DESC.
  - get_active_news()     Retorna solo las noticias activas (para la marquesina).
  - create_news()         Crea una noticia nueva.
  - toggle_news()         Activa o desactiva una noticia.
  - delete_news()         Elimina una noticia.
"""

import uuid as _uuid
from archer.db import get_connection


def list_news() -> list[dict]:
    """Retorna todas las noticias ordenadas por created_at DESC."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, title, content, active, created_at FROM news ORDER BY created_at DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def get_active_news() -> list[dict]:
    """Retorna noticias activas para el ticker de la Home."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT title, content FROM news WHERE active = 1 ORDER BY created_at DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def create_news(title: str, content: str) -> dict:
    """Crea una noticia. Retorna el dict de la noticia o {"error": ...}."""
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or len(title) > 200:
        return {"error": "El título debe tener entre 1 y 200 caracteres.", "field": "title"}
    if not content or len(content) > 1000:
        return {"error": "El contenido debe tener entre 1 y 1000 caracteres.", "field": "content"}

    conn = get_connection()
    news_id = str(_uuid.uuid4())
    conn.execute(
        "INSERT INTO news (id, title, content, active) VALUES (?, ?, ?, 1)",
        (news_id, title, content),
    )
    try:
        conn.commit()
    except Exception:
        pass
    cursor = conn.execute("SELECT * FROM news WHERE id = ?", (news_id,))
    return dict(cursor.fetchone())


def toggle_news(news_id: str) -> dict:
    """Alterna active entre 0 y 1. Retorna {} o {"error": ...}."""
    conn = get_connection()
    cursor = conn.execute("SELECT active FROM news WHERE id = ?", (news_id,))
    row = cursor.fetchone()
    if row is None:
        return {"error": "Noticia no encontrada.", "status_code": 404}
    new_val = 0 if row["active"] else 1
    conn.execute("UPDATE news SET active = ? WHERE id = ?", (new_val, news_id))
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def delete_news(news_id: str) -> dict:
    """Elimina una noticia. Retorna {} o {"error": ...}."""
    conn = get_connection()
    cursor = conn.execute("SELECT id FROM news WHERE id = ?", (news_id,))
    if cursor.fetchone() is None:
        return {"error": "Noticia no encontrada.", "status_code": 404}
    conn.execute("DELETE FROM news WHERE id = ?", (news_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {}
