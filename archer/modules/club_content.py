"""
club_content.py — CRUD para banners, noticias y recursos del club.

Tablas:
  club_banners              — imágenes del carrusel home
  club_news                 — noticias/artículos del club
  club_resource_categories  — categorías de recursos (creadas por el admin)
  club_resources            — documentos y archivos descargables

Todas las funciones son puras (sin estado) y operan sobre la conexión
singleton de db.get_connection().
"""

from __future__ import annotations

import uuid
from datetime import datetime

from archer.db import get_connection


# ──────────────────────────────────────────────────────────────────────────────
# BANNERS
# ──────────────────────────────────────────────────────────────────────────────

def list_banners(active_only: bool = False) -> list[dict]:
    """Retorna todos los banners ordenados por position ASC."""
    conn = get_connection()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM club_banners WHERE is_active = 1 ORDER BY position ASC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM club_banners ORDER BY position ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def create_banner(
    image_url: str,
    title: str = "",
    link_type: str = "none",
    link_value: str = "",
) -> dict:
    """Crea un banner nuevo. Retorna el dict del banner creado o {"error": ...}."""
    if not image_url:
        return {"error": "La URL de imagen es requerida.", "field": "image_url"}

    conn = get_connection()

    # Posición al final
    row = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM club_banners").fetchone()
    next_pos = row["next_pos"] if row else 0

    banner_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO club_banners (id, image_url, title, link_type, link_value, position)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (banner_id, image_url, title or "", link_type or "none", link_value or "", next_pos),
    )
    try:
        conn.commit()
    except Exception:
        pass

    row = conn.execute("SELECT * FROM club_banners WHERE id = ?", (banner_id,)).fetchone()
    return dict(row)


def delete_banner(banner_id: str) -> dict:
    """Elimina un banner. Retorna {} en éxito o {"error": ...}."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM club_banners WHERE id = ?", (banner_id,)).fetchone()
    if not row:
        return {"error": "Banner no encontrado.", "status_code": 404}
    conn.execute("DELETE FROM club_banners WHERE id = ?", (banner_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def toggle_banner(banner_id: str) -> dict:
    """Activa o desactiva un banner. Retorna el nuevo estado."""
    conn = get_connection()
    row = conn.execute("SELECT id, is_active FROM club_banners WHERE id = ?", (banner_id,)).fetchone()
    if not row:
        return {"error": "Banner no encontrado.", "status_code": 404}
    new_val = 0 if row["is_active"] else 1
    conn.execute("UPDATE club_banners SET is_active = ? WHERE id = ?", (new_val, banner_id))
    try:
        conn.commit()
    except Exception:
        pass
    return {"is_active": new_val}


def move_banner(banner_id: str, direction: str) -> dict:
    """Mueve un banner hacia arriba ('up') o hacia abajo ('down') en el orden."""
    if direction not in ("up", "down"):
        return {"error": "Dirección inválida."}

    conn = get_connection()
    banners = conn.execute(
        "SELECT id, position FROM club_banners ORDER BY position ASC"
    ).fetchall()
    ids = [b["id"] for b in banners]

    if banner_id not in ids:
        return {"error": "Banner no encontrado.", "status_code": 404}

    idx = ids.index(banner_id)
    if direction == "up" and idx == 0:
        return {}
    if direction == "down" and idx == len(ids) - 1:
        return {}

    swap_idx = idx - 1 if direction == "up" else idx + 1
    id_a, id_b = ids[idx], ids[swap_idx]
    pos_a = banners[idx]["position"]
    pos_b = banners[swap_idx]["position"]

    conn.execute("UPDATE club_banners SET position = ? WHERE id = ?", (pos_b, id_a))
    conn.execute("UPDATE club_banners SET position = ? WHERE id = ?", (pos_a, id_b))
    try:
        conn.commit()
    except Exception:
        pass
    return {}


# ──────────────────────────────────────────────────────────────────────────────
# NOTICIAS
# ──────────────────────────────────────────────────────────────────────────────

def list_news(published_only: bool = False) -> list[dict]:
    """Retorna noticias ordenadas por published_at DESC, luego created_at DESC."""
    conn = get_connection()
    if published_only:
        rows = conn.execute(
            """
            SELECT * FROM club_news
            WHERE status = 'published'
            ORDER BY COALESCE(published_at, created_at) DESC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM club_news
            ORDER BY COALESCE(published_at, created_at) DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_news_item(news_id: str) -> dict | None:
    """Retorna una noticia por ID, o None si no existe."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM club_news WHERE id = ?", (news_id,)).fetchone()
    return dict(row) if row else None


def create_news_item(
    title: str,
    excerpt: str = "",
    body_html: str = "",
    cover_url: str = "",
    status: str = "draft",
    published_at: str = "",
) -> dict:
    """Crea una noticia. Retorna el dict creado o {"error": ...}."""
    if not title or len(title) > 300:
        return {"error": "El título es requerido y debe tener menos de 300 caracteres.", "field": "title"}
    if status not in ("draft", "published"):
        status = "draft"

    now = datetime.utcnow().isoformat()
    news_id = str(uuid.uuid4())
    pub_at = published_at or (now if status == "published" else None)

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO club_news (id, title, excerpt, body_html, cover_url, status, published_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (news_id, title, excerpt or "", body_html or "", cover_url or "", status, pub_at, now, now),
    )
    try:
        conn.commit()
    except Exception:
        pass

    return dict(conn.execute("SELECT * FROM club_news WHERE id = ?", (news_id,)).fetchone())


def update_news_item(
    news_id: str,
    title: str,
    excerpt: str = "",
    body_html: str = "",
    cover_url: str = "",
    status: str = "draft",
    published_at: str = "",
) -> dict:
    """Actualiza una noticia existente. Retorna {} en éxito o {"error": ...}."""
    if not title or len(title) > 300:
        return {"error": "El título es requerido y debe tener menos de 300 caracteres.", "field": "title"}
    if status not in ("draft", "published"):
        status = "draft"

    conn = get_connection()
    row = conn.execute("SELECT id, status, published_at FROM club_news WHERE id = ?", (news_id,)).fetchone()
    if not row:
        return {"error": "Noticia no encontrada.", "status_code": 404}

    now = datetime.utcnow().isoformat()
    # Si se publica por primera vez, registrar published_at
    existing_pub = row["published_at"]
    if status == "published" and not existing_pub and not published_at:
        pub_at = now
    else:
        pub_at = published_at or existing_pub

    conn.execute(
        """
        UPDATE club_news
        SET title = ?, excerpt = ?, body_html = ?, cover_url = ?,
            status = ?, published_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (title, excerpt or "", body_html or "", cover_url or "", status, pub_at, now, news_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def delete_news_item(news_id: str) -> dict:
    """Elimina una noticia. Retorna {} en éxito."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM club_news WHERE id = ?", (news_id,)).fetchone()
    if not row:
        return {"error": "Noticia no encontrada.", "status_code": 404}
    conn.execute("DELETE FROM club_news WHERE id = ?", (news_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def toggle_news_status(news_id: str) -> dict:
    """Alterna entre draft y published. Si se publica, registra published_at."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id, status, published_at FROM club_news WHERE id = ?", (news_id,)
    ).fetchone()
    if not row:
        return {"error": "Noticia no encontrada.", "status_code": 404}

    now = datetime.utcnow().isoformat()
    if row["status"] == "published":
        new_status = "draft"
        pub_at = row["published_at"]  # conservar fecha original
    else:
        new_status = "published"
        pub_at = row["published_at"] or now

    conn.execute(
        "UPDATE club_news SET status = ?, published_at = ?, updated_at = ? WHERE id = ?",
        (new_status, pub_at, now, news_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"status": new_status}


# ──────────────────────────────────────────────────────────────────────────────
# CATEGORÍAS DE RECURSOS
# ──────────────────────────────────────────────────────────────────────────────

def list_resource_categories() -> list[dict]:
    """Retorna todas las categorías de recursos ordenadas por position ASC."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM club_resource_categories ORDER BY position ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def create_resource_category(name: str) -> dict:
    """Crea una categoría de recursos. Retorna el dict creado o {"error": ...}."""
    if not name or len(name) > 100:
        return {"error": "El nombre es requerido (máx. 100 caracteres).", "field": "name"}

    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM club_resource_categories"
    ).fetchone()
    next_pos = row["next_pos"] if row else 0

    cat_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO club_resource_categories (id, name, position) VALUES (?, ?, ?)",
        (cat_id, name, next_pos),
    )
    try:
        conn.commit()
    except Exception:
        pass

    row = conn.execute(
        "SELECT * FROM club_resource_categories WHERE id = ?", (cat_id,)
    ).fetchone()
    return dict(row)


def delete_resource_category(cat_id: str) -> dict:
    """Elimina una categoría. Los recursos de esa categoría quedan con category_id = NULL."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM club_resource_categories WHERE id = ?", (cat_id,)
    ).fetchone()
    if not row:
        return {"error": "Categoría no encontrada.", "status_code": 404}

    # Desvincular recursos
    conn.execute(
        "UPDATE club_resources SET category_id = NULL WHERE category_id = ?", (cat_id,)
    )
    conn.execute("DELETE FROM club_resource_categories WHERE id = ?", (cat_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {}


# ──────────────────────────────────────────────────────────────────────────────
# RECURSOS
# ──────────────────────────────────────────────────────────────────────────────

def list_resources(active_only: bool = False) -> list[dict]:
    """
    Retorna recursos con su categoría, ordenados por category position,
    luego resource position ASC.
    """
    conn = get_connection()
    base = """
        SELECT r.*,
               COALESCE(c.name, 'Sin categoría') AS category_name,
               COALESCE(c.position, 9999)         AS cat_position
        FROM club_resources r
        LEFT JOIN club_resource_categories c ON c.id = r.category_id
    """
    if active_only:
        rows = conn.execute(base + " WHERE r.is_active = 1 ORDER BY cat_position ASC, r.position ASC").fetchall()
    else:
        rows = conn.execute(base + " ORDER BY cat_position ASC, r.position ASC").fetchall()
    return [dict(r) for r in rows]


def list_resources_grouped(active_only: bool = False) -> list[dict]:
    """
    Retorna recursos agrupados por categoría.
    [{"category_id": ..., "category_name": ..., "resources": [...]}]
    """
    resources = list_resources(active_only=active_only)
    categories_seen: dict = {}
    result: list[dict] = []

    for r in resources:
        cid = r.get("category_id") or "__none__"
        cname = r.get("category_name") or "Sin categoría"
        if cid not in categories_seen:
            categories_seen[cid] = len(result)
            result.append({"category_id": cid, "category_name": cname, "resources": []})
        result[categories_seen[cid]]["resources"].append(r)

    return result


def create_resource(
    title: str,
    file_url: str,
    description: str = "",
    category_id: str = "",
    file_type: str = "link",
) -> dict:
    """Crea un recurso. Retorna el dict creado o {"error": ...}."""
    if not title:
        return {"error": "El título es requerido.", "field": "title"}
    if not file_url:
        return {"error": "La URL/archivo es requerido.", "field": "file_url"}
    if file_type not in ("pdf", "docx", "zip", "link", "xlsx", "other"):
        file_type = "link"

    conn = get_connection()
    row = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM club_resources").fetchone()
    next_pos = row["next_pos"] if row else 0

    res_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO club_resources (id, category_id, title, description, file_url, file_type, position)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (res_id, category_id or None, title, description or "", file_url, file_type, next_pos),
    )
    try:
        conn.commit()
    except Exception:
        pass

    row = conn.execute("SELECT * FROM club_resources WHERE id = ?", (res_id,)).fetchone()
    return dict(row)


def delete_resource(res_id: str) -> dict:
    """Elimina un recurso. Retorna {} en éxito."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM club_resources WHERE id = ?", (res_id,)).fetchone()
    if not row:
        return {"error": "Recurso no encontrado.", "status_code": 404}
    conn.execute("DELETE FROM club_resources WHERE id = ?", (res_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def toggle_resource(res_id: str) -> dict:
    """Activa/desactiva la visibilidad de un recurso."""
    conn = get_connection()
    row = conn.execute("SELECT id, is_active FROM club_resources WHERE id = ?", (res_id,)).fetchone()
    if not row:
        return {"error": "Recurso no encontrado.", "status_code": 404}
    new_val = 0 if row["is_active"] else 1
    conn.execute("UPDATE club_resources SET is_active = ? WHERE id = ?", (new_val, res_id))
    try:
        conn.commit()
    except Exception:
        pass
    return {"is_active": new_val}
