"""
Leaderboard_Module — cálculo de clasificación y broadcasting SSE.

Expone:
  - compute_leaderboard(tournament_id)  Calcula y retorna el leaderboard completo.
  - broadcast_update(tournament_id)     Encola una señal de actualización.
  - sse_stream(tournament_id)           Generador SSE que emite eventos al cliente.

Requerimientos cubiertos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

import json
import queue

from archer.db import get_connection

# ---------------------------------------------------------------------------
# Estado de colas en memoria (una Queue por torneo)
# ---------------------------------------------------------------------------
_queues: dict[str, queue.Queue] = {}

# Timeout del heartbeat SSE en segundos (Req 6.5)
_HEARTBEAT_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Cálculo del leaderboard (Req 6.3, 6.4)
# ---------------------------------------------------------------------------

def compute_leaderboard(tournament_id: str) -> list[dict]:
    """Calcula el leaderboard completo para el torneo dado.

    Para cada categoría del torneo:
    - Obtiene todos los arqueros inscritos (via registrations).
    - Calcula total_points, x_count y ten_count desde la tabla scores.
    - Ordena: total_points DESC, x_count DESC, ten_count DESC (Req 6.3).
    - Asigna posición 1-based dentro de cada categoría (Req 6.4).
    - Incluye arqueros con 0 scores (total_points=0, x_count=0, ten_count=0).
    - Incluye categorías sin arqueros inscritos (entries=[]).

    Retorna lista de dicts con estructura:
    [
      {
        "category_id": str,
        "bow_type": str,
        "distance": str,
        "gender": str,
        "entries": [
          {
            "position": int,
            "archer_id": str,
            "name": str,
            "total_points": int,
            "x_count": int,
            "ten_count": int,
          }
        ]
      }
    ]
    """
    conn = get_connection()

    # 1. Obtener todas las categorías del torneo
    cursor = conn.execute(
        """
        SELECT id, bow_type, distance, gender
        FROM categories
        WHERE tournament_id = ?
        """,
        (tournament_id,),
    )
    categories = [dict(row) for row in cursor.fetchall()]

    result = []

    for cat in categories:
        cat_id = cat["id"]

        # 2. Obtener todos los arqueros inscritos en esta categoría
        cursor = conn.execute(
            """
            SELECT a.id AS archer_id, a.name, a.photo_url
            FROM registrations r
            JOIN archers a ON a.id = r.archer_id
            WHERE r.tournament_id = ?
              AND r.category_id   = ?
            """,
            (tournament_id, cat_id),
        )
        archers = [dict(row) for row in cursor.fetchall()]

        entries = []
        for archer in archers:
            archer_id = archer["archer_id"]

            # 3. Calcular métricas desde scores
            cursor = conn.execute(
                """
                SELECT
                    COALESCE(SUM(points), 0)                          AS total_points,
                    COALESCE(SUM(CASE WHEN arrow_val = 'X'  THEN 1 ELSE 0 END), 0) AS x_count,
                    COALESCE(SUM(CASE WHEN arrow_val = '10' THEN 1 ELSE 0 END), 0) AS ten_count
                FROM scores
                WHERE tournament_id = ?
                  AND archer_id     = ?
                """,
                (tournament_id, archer_id),
            )
            row = cursor.fetchone()
            entries.append(
                {
                    "archer_id": archer_id,
                    "name": archer["name"],
                    "photo_url": archer.get("photo_url") or "",
                    "total_points": int(row["total_points"]),
                    "x_count": int(row["x_count"]),
                    "ten_count": int(row["ten_count"]),
                }
            )

        # 4. Ordenar: total_points DESC, x_count DESC, ten_count DESC (Req 6.3)
        entries.sort(
            key=lambda e: (-e["total_points"], -e["x_count"], -e["ten_count"])
        )

        # 5. Asignar posición 1-based (Req 6.4)
        for idx, entry in enumerate(entries, start=1):
            entry["position"] = idx

        result.append(
            {
                "category_id": cat_id,
                "bow_type": cat["bow_type"],
                "distance": cat["distance"],
                "gender": cat["gender"],
                "entries": entries,
            }
        )

    return result


# ---------------------------------------------------------------------------
# Broadcasting (Req 6.2, 6.7)
# ---------------------------------------------------------------------------

def broadcast_update(tournament_id: str) -> None:
    """Encola una señal de actualización para el torneo dado.

    Obtiene o crea la Queue asociada a tournament_id y pone el id en ella.
    La operación es no bloqueante (put_nowait).
    """
    if tournament_id not in _queues:
        _queues[tournament_id] = queue.Queue()
    _queues[tournament_id].put_nowait(tournament_id)


# ---------------------------------------------------------------------------
# Generador SSE (Req 6.1, 6.5, 6.6)
# ---------------------------------------------------------------------------

def sse_stream(tournament_id: str):
    """Generador que produce eventos SSE para el leaderboard en vivo.

    Protocolo:
    1. Al conectar: emite inmediatamente el estado completo del leaderboard
       como evento 'leaderboard' (Req 6.6).
    2. Espera en la queue con timeout de 30 s:
       - Si llega un item: recalcula y emite evento 'leaderboard' (Req 6.2).
       - Si timeout: emite evento 'heartbeat' (Req 6.5).
    3. Maneja GeneratorExit / StopIteration de forma limpia.

    Formato de evento SSE:
        event: leaderboard
        data: {"tournament_id": "...", "categories": [...]}

        event: heartbeat
        data: {}

    (doble newline al final de cada evento)
    """
    # Asegurar que exista la queue para este torneo
    if tournament_id not in _queues:
        _queues[tournament_id] = queue.Queue()
    q = _queues[tournament_id]

    def _leaderboard_event() -> str:
        categories = compute_leaderboard(tournament_id)
        payload = json.dumps(
            {"tournament_id": tournament_id, "categories": categories},
            ensure_ascii=False,
        )
        return f"event: leaderboard\ndata: {payload}\n\n"

    def _heartbeat_event() -> str:
        return "event: heartbeat\ndata: {}\n\n"

    try:
        # Req 6.6 — estado completo como primer evento
        yield _leaderboard_event()

        while True:
            try:
                q.get(timeout=_HEARTBEAT_TIMEOUT)
                # Un item en la queue indica que hay una actualización
                yield _leaderboard_event()
            except queue.Empty:
                # Timeout de 30 s → heartbeat (Req 6.5)
                yield _heartbeat_event()

    except (GeneratorExit, StopIteration):
        # El cliente se desconectó; terminar limpiamente
        return
