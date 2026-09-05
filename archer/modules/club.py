"""
Club_Module — configuración de branding del club (multi-tenant).

Expone:
  - get_club_settings()   Retorna el dict de configuración actual.
  - save_club_settings()  Persiste los cambios de branding.
"""

from archer.db import get_connection

_DEFAULTS = {
    "club_name":    "KiroArchery",
    "hero_title":   "Tu torneo de arquería, en tiempo real",
    "hero_subtitle": "Cargá flechas, seguí el leaderboard en vivo y consultá el ranking histórico.",
    "ticker_text":  "🏹 Bienvenido · Registrá tu puntaje · ¡Buena puntería!",
    "color_from":   "#166534",
    "color_to":     "#16a34a",
}


def get_club_settings() -> dict:
    """Retorna la configuración del club. Nunca falla — usa defaults si hay error."""
    try:
        conn = get_connection()
        cursor = conn.execute("SELECT * FROM club_settings WHERE id = 'default'")
        row = cursor.fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return dict(_DEFAULTS)


def save_club_settings(
    club_name: str,
    hero_title: str,
    hero_subtitle: str,
    ticker_text: str,
    color_from: str,
    color_to: str,
) -> dict:
    """Persiste la configuración del club. Retorna {} en éxito o {"error": ...}."""
    # Validaciones básicas
    if not club_name or len(club_name) > 100:
        return {"error": "El nombre del club debe tener entre 1 y 100 caracteres.", "field": "club_name"}
    if not hero_title or len(hero_title) > 200:
        return {"error": "El título del hero debe tener entre 1 y 200 caracteres.", "field": "hero_title"}

    # Validar que los colores son hex válidos (#rrggbb)
    import re
    hex_re = re.compile(r'^#[0-9a-fA-F]{6}$')
    if not hex_re.match(color_from):
        return {"error": "El color inicial debe ser un valor hexadecimal (#rrggbb).", "field": "color_from"}
    if not hex_re.match(color_to):
        return {"error": "El color final debe ser un valor hexadecimal (#rrggbb).", "field": "color_to"}

    try:
        conn = get_connection()
        conn.execute(
            """
            UPDATE club_settings
            SET club_name     = ?,
                hero_title    = ?,
                hero_subtitle = ?,
                ticker_text   = ?,
                color_from    = ?,
                color_to      = ?,
                updated_at    = CURRENT_TIMESTAMP
            WHERE id = 'default'
            """,
            (club_name, hero_title, hero_subtitle, ticker_text, color_from, color_to),
        )
        try:
            conn.commit()
        except Exception:
            pass
        return {}
    except Exception as exc:
        return {"error": f"Error al guardar: {exc}"}
