"""
auth.py — Autenticación de arqueros por email/contraseña y Google OAuth.

Expone:
    register_with_email(first_name, last_name, email, password) → dict
    login_with_email(email, password)                           → dict
    find_or_create_google_archer(profile)                       → dict

Los dicts de éxito contienen los campos del arquero.
Los dicts de error contienen {"error": "...", "field": "..."}.
"""

from __future__ import annotations

import re
import uuid
import time

from archer.db import get_connection

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_EMAIL_RE   = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PW_LEN = 8

# Bloqueo por intentos fallidos (compartido con PIN pero clave por email)
_email_lockout: dict[str, tuple[int, float]] = {}
_MAX_ATTEMPTS    = 5
_BLOCK_SECONDS   = 300   # 5 minutos


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    import bcrypt  # import diferido — no falla si no está instalado en dev
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_password(password: str, hashed: str) -> bool:
    import bcrypt
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _row_to_archer(row) -> dict:
    d = dict(row)
    # Construir nombre completo para sesión
    if d.get("first_name") and d.get("last_name"):
        d["name"] = f"{d['first_name']} {d['last_name']}"
    elif d.get("first_name"):
        d["name"] = d["first_name"]
    return d


# ---------------------------------------------------------------------------
# Registro con email
# ---------------------------------------------------------------------------

def register_with_email(
    first_name: str,
    last_name: str,
    email: str,
    password: str,
) -> dict:
    """
    Crea un nuevo arquero con email + contraseña.
    Retorna dict del arquero en caso de éxito, dict con 'error' si falla.
    """
    # Validaciones
    first_name = (first_name or "").strip()
    last_name  = (last_name  or "").strip()
    email      = (email      or "").strip().lower()
    password   = (password   or "")

    if not first_name:
        return {"error": "El nombre es obligatorio.", "field": "first_name"}
    if not last_name:
        return {"error": "El apellido es obligatorio.", "field": "last_name"}
    if not _EMAIL_RE.match(email):
        return {"error": "El email no es válido.", "field": "email"}
    if len(password) < _MIN_PW_LEN:
        return {"error": f"La contraseña debe tener al menos {_MIN_PW_LEN} caracteres.", "field": "password"}

    conn = get_connection()

    # Verificar duplicado
    existing = conn.execute(
        "SELECT id FROM archers WHERE email = ?", (email,)
    ).fetchone()
    if existing:
        return {"error": "Ya existe una cuenta con ese email.", "field": "email"}

    archer_id     = str(uuid.uuid4())
    password_hash = _hash_password(password)
    full_name     = f"{first_name} {last_name}"

    conn.execute(
        """
        INSERT INTO archers
            (id, name, first_name, last_name, email, password_hash, auth_provider, pin, status)
        VALUES (?, ?, ?, ?, ?, ?, 'email', ?, 'pending')
        """,
        (archer_id, full_name, first_name, last_name, email, password_hash,
         f"__email__{archer_id[:8]}"),
    )
    try:
        conn.commit()
    except Exception:
        pass

    row = conn.execute(
        "SELECT * FROM archers WHERE id = ?", (archer_id,)
    ).fetchone()
    return _row_to_archer(row) if row else {"error": "Error al crear la cuenta."}


# ---------------------------------------------------------------------------
# Login con email
# ---------------------------------------------------------------------------

def login_with_email(email: str, password: str) -> dict:
    """
    Autentica un arquero por email + contraseña.
    Implementa bloqueo tras 5 intentos fallidos (5 minutos).
    """
    email    = (email    or "").strip().lower()
    password = (password or "")

    if not email or not password:
        return {"error": "Email y contraseña son obligatorios.", "field": "email"}

    # Verificar bloqueo
    attempts, block_until = _email_lockout.get(email, (0, 0.0))
    if block_until > time.time():
        mins = max(1, int((block_until - time.time()) / 60) + 1)
        return {"error": f"Demasiados intentos. Esperá {mins} minutos.", "blocked": True}

    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM archers WHERE email = ?", (email,)
    ).fetchone()

    # Error genérico — no revelar si el email existe
    if row is None or not row["password_hash"]:
        attempts += 1
        if attempts >= _MAX_ATTEMPTS:
            _email_lockout[email] = (attempts, time.time() + _BLOCK_SECONDS)
        else:
            _email_lockout[email] = (attempts, 0.0)
        return {"error": "Email o contraseña incorrectos."}

    if not _check_password(password, row["password_hash"]):
        attempts += 1
        if attempts >= _MAX_ATTEMPTS:
            _email_lockout[email] = (attempts, time.time() + _BLOCK_SECONDS)
        else:
            _email_lockout[email] = (attempts, 0.0)
        return {"error": "Email o contraseña incorrectos."}

    # Éxito — resetear intentos
    _email_lockout[email] = (0, 0.0)
    result = _row_to_archer(row)
    # Indicar si está pendiente de aprobación
    result["is_pending"] = (row["status"] == "pending")
    return result


# ---------------------------------------------------------------------------
# Google OAuth — crear o encontrar arquero
# ---------------------------------------------------------------------------

def find_or_create_google_archer(profile: dict) -> dict:
    """
    Busca o crea un arquero a partir del perfil de Google.

    profile esperado:
        {
            "sub":          "1234567890",       ← Google ID único
            "email":        "usuario@gmail.com",
            "given_name":   "Juan",
            "family_name":  "García",
            "name":         "Juan García",
            "picture":      "https://...",      ← URL foto (opcional)
        }
    """
    google_id  = str(profile.get("sub", ""))
    email      = str(profile.get("email", "")).strip().lower()
    given      = str(profile.get("given_name") or profile.get("name", "")).strip()
    family     = str(profile.get("family_name", "")).strip()
    picture    = str(profile.get("picture", ""))
    full_name  = f"{given} {family}".strip() or email.split("@")[0]

    if not google_id:
        return {"error": "Perfil de Google inválido."}

    conn = get_connection()

    # 1. Buscar por google_id
    row = conn.execute(
        "SELECT * FROM archers WHERE google_id = ?", (google_id,)
    ).fetchone()
    if row:
        result = _row_to_archer(row)
        result["is_pending"] = (row["status"] == "pending")
        return result

    # 2. Buscar por email — unificar cuenta existente
    if email:
        row = conn.execute(
            "SELECT * FROM archers WHERE email = ?", (email,)
        ).fetchone()
        if row:
            # Actualizar con google_id y foto si no tiene
            conn.execute(
                """
                UPDATE archers
                SET google_id     = ?,
                    auth_provider = 'google',
                    photo_url     = COALESCE(NULLIF(photo_url,''), ?)
                WHERE id = ?
                """,
                (google_id, picture or None, row["id"]),
            )
            try:
                conn.commit()
            except Exception:
                pass
            row = conn.execute(
                "SELECT * FROM archers WHERE id = ?", (row["id"],)
            ).fetchone()
            result = _row_to_archer(row)
            result["is_pending"] = (row["status"] == "pending")
            return result

    # 3. Crear arquero nuevo — pending hasta aprobación del admin
    archer_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO archers
            (id, name, first_name, last_name, email, google_id,
             auth_provider, photo_url, pin, status)
        VALUES (?, ?, ?, ?, ?, ?, 'google', ?, ?, 'pending')
        """,
        (archer_id, full_name, given, family, email or None,
         google_id, picture or None,
         f"__google__{archer_id[:8]}"),
    )
    try:
        conn.commit()
    except Exception:
        pass

    row = conn.execute(
        "SELECT * FROM archers WHERE id = ?", (archer_id,)
    ).fetchone()
    if row:
        result = _row_to_archer(row)
        result["is_pending"] = True  # siempre pending al crear
        return result
    return {"error": "Error al crear la cuenta con Google."}
