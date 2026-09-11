"""
profile.py — Perfil extendido y configuración de equipo del arquero.

Expone:
  - get_profile(archer_id)          Retorna perfil extendido (crea uno vacío si no existe).
  - save_profile(archer_id, ...)    Persiste datos personales y banner.
  - upload_banner(archer_id, data)  Sube banner a Cloudinary y actualiza la URL.

  - list_setups(archer_id)          Lista todos los setups de equipo.
  - get_setup(setup_id, archer_id)  Retorna un setup concreto (verificando pertenencia).
  - create_setup(archer_id, ...)    Crea un nuevo setup.
  - update_setup(setup_id, archer_id, ...) Modifica un setup existente.
  - delete_setup(setup_id, archer_id)      Elimina un setup (soft: is_active=0).
  - set_active_setup(setup_id, archer_id)  Marca un setup como activo (deselecciona resto).
"""

from __future__ import annotations

import io
import json
import os
import uuid as _uuid

from archer.db import get_connection

# Valores permitidos para validaciones
_HAND_OPTIONS     = ("Diestro", "Zurdo")
_BOW_TYPE_OPTIONS = ("Recurvo", "Compuesto", "Barebow", "Longbow", "Tradicional")


# ---------------------------------------------------------------------------
# Perfil personal
# ---------------------------------------------------------------------------

def get_profile(archer_id: str) -> dict:
    """Retorna el perfil extendido. Inserta fila vacía si no existe."""
    conn = get_connection()

    # Traer perfil + datos base del arquero en un solo JOIN
    cursor = conn.execute(
        """
        SELECT a.id, a.name, a.photo_url,
               COALESCE(p.nickname,       '')        AS nickname,
               COALESCE(p.club,           '')        AS club,
               COALESCE(p.dominant_hand,  'Diestro') AS dominant_hand,
               COALESCE(p.bow_category,   '')        AS bow_category,
               COALESCE(p.season_goal,    '')        AS season_goal,
               COALESCE(p.banner_url,     '')        AS banner_url
        FROM archers a
        LEFT JOIN archer_profiles p ON p.archer_id = a.id
        WHERE a.id = ?
        """,
        (archer_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return {}

    # Asegurar que existe la fila en archer_profiles (INSERT OR IGNORE)
    conn.execute(
        "INSERT OR IGNORE INTO archer_profiles (archer_id) VALUES (?)",
        (archer_id,),
    )
    try:
        conn.commit()
    except Exception:
        pass

    return dict(row)


def save_profile(
    archer_id: str,
    name: str,
    nickname: str,
    club: str,
    dominant_hand: str,
    bow_category: str,
    season_goal: str,
) -> dict:
    """Persiste los datos editables del perfil. Retorna {} en éxito o {"error": ...}."""
    name = (name or "").strip()
    if not name or len(name) > 100:
        return {"error": "El nombre debe tener entre 1 y 100 caracteres.", "field": "name"}

    if dominant_hand and dominant_hand not in _HAND_OPTIONS:
        return {"error": "Mano dominante inválida.", "field": "dominant_hand"}

    conn = get_connection()

    # Actualizar nombre en tabla archers
    conn.execute("UPDATE archers SET name = ? WHERE id = ?", (name, archer_id))

    # Upsert en archer_profiles
    conn.execute(
        """
        INSERT INTO archer_profiles (archer_id, nickname, club, dominant_hand, bow_category, season_goal, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(archer_id) DO UPDATE SET
            nickname      = excluded.nickname,
            club          = excluded.club,
            dominant_hand = excluded.dominant_hand,
            bow_category  = excluded.bow_category,
            season_goal   = excluded.season_goal,
            updated_at    = CURRENT_TIMESTAMP
        """,
        (archer_id, nickname[:80] if nickname else "",
         club[:100] if club else "",
         dominant_hand or "Diestro",
         bow_category[:50] if bow_category else "",
         season_goal[:200] if season_goal else ""),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def upload_banner(archer_id: str, file_data: bytes, filename: str) -> dict:
    """Sube la imagen de banner a Cloudinary (o disco local como fallback). Retorna {"url": ...} o {"error": ...}."""
    cloudinary_url = os.environ.get("CLOUDINARY_URL")

    if cloudinary_url:
        try:
            import cloudinary          # type: ignore
            import cloudinary.uploader  # type: ignore
            cloudinary.config(cloudinary_url=cloudinary_url)
            result = cloudinary.uploader.upload(
                io.BytesIO(file_data),
                public_id=f"archer_banners/{archer_id}",
                overwrite=True,
                resource_type="image",
                transformation=[{"width": 1200, "height": 400, "crop": "fill", "gravity": "center"}],
            )
            url = result.get("secure_url", "")
        except Exception as exc:
            return {"error": f"Error al subir el banner a Cloudinary: {exc}"}
    else:
        # Fallback: disco local
        try:
            import os as _os
            from flask import current_app
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
            fname = f"banner_{archer_id}.{ext}"
            banners_dir = _os.path.join(current_app.root_path, "static", "banners")
            _os.makedirs(banners_dir, exist_ok=True)
            with open(_os.path.join(banners_dir, fname), "wb") as f:
                f.write(file_data)
            url = f"/static/banners/{fname}"
        except Exception as exc:
            return {"error": f"Error al guardar el banner: {exc}"}

    # Persistir URL
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO archer_profiles (archer_id, banner_url, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(archer_id) DO UPDATE SET
            banner_url = excluded.banner_url,
            updated_at = CURRENT_TIMESTAMP
        """,
        (archer_id, url),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"url": url}


# ---------------------------------------------------------------------------
# Setups de equipo
# ---------------------------------------------------------------------------

def _parse_sight_marks(raw: str | None) -> list[dict]:
    """Parsea el JSON de sight_marks. Retorna lista vacía si falla."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _row_to_setup(row: dict) -> dict:
    """Convierte una fila DB en dict con sight_marks ya parseado."""
    d = dict(row)
    d["sight_marks"] = _parse_sight_marks(d.get("sight_marks"))
    return d


def list_setups(archer_id: str) -> list[dict]:
    """Retorna todos los setups activos del arquero, ordenados por nombre."""
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT id, archer_id, name, bow_type, draw_weight, draw_length,
               string_material, arrow_model, arrow_spine, arrow_length,
               point_weight, vanes, nock, sight_marks, is_active, created_at
        FROM bow_setups
        WHERE archer_id = ? AND is_active = 1
        ORDER BY name ASC
        """,
        (archer_id,),
    )
    return [_row_to_setup(r) for r in cursor.fetchall()]


def get_setup(setup_id: str, archer_id: str) -> dict | None:
    """Retorna un setup concreto verificando que pertenece al arquero."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM bow_setups WHERE id = ? AND archer_id = ? AND is_active = 1",
        (setup_id, archer_id),
    )
    row = cursor.fetchone()
    return _row_to_setup(row) if row else None


def create_setup(
    archer_id: str,
    name: str,
    bow_type: str,
    draw_weight: str,
    draw_length: str,
    string_material: str,
    arrow_model: str,
    arrow_spine: str,
    arrow_length: str,
    point_weight: str,
    vanes: str,
    nock: str,
    sight_marks: list[dict] | None = None,
) -> dict:
    """Crea un nuevo setup. Retorna {"id": ...} en éxito o {"error": ...}."""
    name = (name or "").strip()
    if not name or len(name) > 100:
        return {"error": "El nombre del setup debe tener entre 1 y 100 caracteres.", "field": "name"}

    if bow_type and bow_type not in _BOW_TYPE_OPTIONS:
        return {"error": "Tipo de arco inválido.", "field": "bow_type"}

    # Convertir numéricos — None si vacío/inválido
    def _float(v: str) -> float | None:
        try:
            return float(v) if v and v.strip() else None
        except (ValueError, TypeError):
            return None

    def _int(v: str) -> int | None:
        try:
            return int(v) if v and v.strip() else None
        except (ValueError, TypeError):
            return None

    setup_id = str(_uuid.uuid4())
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO bow_setups (
            id, archer_id, name, bow_type,
            draw_weight, draw_length, string_material,
            arrow_model, arrow_spine, arrow_length, point_weight,
            vanes, nock, sight_marks, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            setup_id, archer_id, name, bow_type or "",
            _float(draw_weight), _float(draw_length), (string_material or "").strip(),
            (arrow_model or "").strip(), (arrow_spine or "").strip(),
            _float(arrow_length), _int(point_weight),
            (vanes or "").strip(), (nock or "").strip(),
            json.dumps(sight_marks or []),
        ),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {"id": setup_id}


def update_setup(
    setup_id: str,
    archer_id: str,
    name: str,
    bow_type: str,
    draw_weight: str,
    draw_length: str,
    string_material: str,
    arrow_model: str,
    arrow_spine: str,
    arrow_length: str,
    point_weight: str,
    vanes: str,
    nock: str,
    sight_marks: list[dict] | None = None,
) -> dict:
    """Modifica un setup existente. Retorna {} en éxito o {"error": ...}."""
    name = (name or "").strip()
    if not name or len(name) > 100:
        return {"error": "El nombre del setup debe tener entre 1 y 100 caracteres.", "field": "name"}

    if bow_type and bow_type not in _BOW_TYPE_OPTIONS:
        return {"error": "Tipo de arco inválido.", "field": "bow_type"}

    def _float(v: str) -> float | None:
        try:
            return float(v) if v and v.strip() else None
        except (ValueError, TypeError):
            return None

    def _int(v: str) -> int | None:
        try:
            return int(v) if v and v.strip() else None
        except (ValueError, TypeError):
            return None

    conn = get_connection()
    cursor = conn.execute(
        "SELECT id FROM bow_setups WHERE id = ? AND archer_id = ? AND is_active = 1",
        (setup_id, archer_id),
    )
    if cursor.fetchone() is None:
        return {"error": "Setup no encontrado.", "status_code": 404}

    conn.execute(
        """
        UPDATE bow_setups SET
            name = ?, bow_type = ?,
            draw_weight = ?, draw_length = ?, string_material = ?,
            arrow_model = ?, arrow_spine = ?, arrow_length = ?,
            point_weight = ?, vanes = ?, nock = ?, sight_marks = ?
        WHERE id = ? AND archer_id = ?
        """,
        (
            name, bow_type or "",
            _float(draw_weight), _float(draw_length), (string_material or "").strip(),
            (arrow_model or "").strip(), (arrow_spine or "").strip(),
            _float(arrow_length), _int(point_weight),
            (vanes or "").strip(), (nock or "").strip(),
            json.dumps(sight_marks or []),
            setup_id, archer_id,
        ),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {}


def delete_setup(setup_id: str, archer_id: str) -> dict:
    """Soft-delete: marca is_active=0. Retorna {} o {"error": ...}."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT id FROM bow_setups WHERE id = ? AND archer_id = ? AND is_active = 1",
        (setup_id, archer_id),
    )
    if cursor.fetchone() is None:
        return {"error": "Setup no encontrado.", "status_code": 404}
    conn.execute(
        "UPDATE bow_setups SET is_active = 0 WHERE id = ? AND archer_id = ?",
        (setup_id, archer_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {}
