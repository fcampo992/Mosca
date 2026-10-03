"""
plotter.py — Módulo de registro de coordenadas de impacto de flechas.

Tablas:
    arrow_plots — coordenadas (x_pct, y_pct) de cada flecha por sesión/tanda.

Expone:
    save_plots(session_type, session_id, archer_id, end_number, arrows)
        Guarda (o reemplaza) todos los plots de una tanda.
        arrows = [{"val": "9", "x": -23.4, "y": 15.2}, ...]

    get_plots_for_end(session_type, session_id, end_number)
        Retorna los plots de una tanda específica.

    get_all_plots_for_session(session_type, session_id, archer_id)
        Retorna TODOS los plots de la sesión (para heatmap de resumen).

    delete_plots_for_end(session_type, session_id, end_number)
        Elimina plots de una tanda (usado al re-enviar la tanda).

    delete_all_plots_for_session(session_type, session_id)
        Elimina todos los plots de la sesión (usado al borrar la sesión).
"""

from __future__ import annotations
import uuid
from archer.db import get_connection


def save_plots(
    session_type: str,
    session_id: str,
    archer_id: str,
    end_number: int,
    arrows: list[dict],
) -> None:
    """
    Guarda los plots de una tanda completa.
    Reemplaza cualquier plot previo para esa tanda (idempotente).

    arrows: lista de dicts con claves 'val', 'x', 'y'
        val — valor de la flecha (X, 10, 9 … M)
        x   — coordenada X en unidades de viewBox (-100..100)
        y   — coordenada Y en unidades de viewBox (-100..100)
    """
    if not arrows:
        return

    conn = get_connection()

    # Borrar plots anteriores de esta tanda (upsert manual)
    conn.execute(
        """
        DELETE FROM arrow_plots
        WHERE session_type = ? AND session_id = ? AND end_number = ?
        """,
        (session_type, session_id, end_number),
    )

    for i, arrow in enumerate(arrows):
        x = float(arrow.get("x", 0))
        y = float(arrow.get("y", 0))
        val = str(arrow.get("val", "M"))
        conn.execute(
            """
            INSERT INTO arrow_plots
                (id, session_type, session_id, archer_id, end_number,
                 arrow_index, x_pct, y_pct, score_val)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), session_type, session_id, archer_id,
             end_number, i, x, y, val),
        )

    try:
        conn.commit()
    except Exception:
        pass


def get_plots_for_end(
    session_type: str,
    session_id: str,
    end_number: int,
) -> list[dict]:
    """Retorna los plots de una tanda ordenados por arrow_index."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT arrow_index, x_pct, y_pct, score_val
        FROM arrow_plots
        WHERE session_type = ? AND session_id = ? AND end_number = ?
        ORDER BY arrow_index ASC
        """,
        (session_type, session_id, end_number),
    ).fetchall()
    return [
        {"index": r["arrow_index"], "x": r["x_pct"], "y": r["y_pct"], "val": r["score_val"]}
        for r in rows
    ]


def get_all_plots_for_session(
    session_type: str,
    session_id: str,
    archer_id: str,
) -> list[dict]:
    """
    Retorna todos los plots de la sesión completa para el heatmap de resumen.
    Incluye end_number para poder agrupar por tanda si se necesita.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT end_number, arrow_index, x_pct, y_pct, score_val
        FROM arrow_plots
        WHERE session_type = ? AND session_id = ? AND archer_id = ?
        ORDER BY end_number ASC, arrow_index ASC
        """,
        (session_type, session_id, archer_id),
    ).fetchall()
    return [
        {
            "end": r["end_number"],
            "index": r["arrow_index"],
            "x": r["x_pct"],
            "y": r["y_pct"],
            "val": r["score_val"],
        }
        for r in rows
    ]


def delete_plots_for_end(
    session_type: str,
    session_id: str,
    end_number: int,
) -> None:
    """Elimina plots de una tanda (al re-enviar o corregir una tanda)."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM arrow_plots WHERE session_type=? AND session_id=? AND end_number=?",
        (session_type, session_id, end_number),
    )
    try:
        conn.commit()
    except Exception:
        pass


def delete_all_plots_for_session(
    session_type: str,
    session_id: str,
) -> None:
    """Elimina todos los plots de una sesión (al borrar la sesión entera)."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM arrow_plots WHERE session_type=? AND session_id=?",
        (session_type, session_id),
    )
    try:
        conn.commit()
    except Exception:
        pass
