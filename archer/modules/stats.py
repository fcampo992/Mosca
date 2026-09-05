"""
Stats_Module — estadísticas de torneo, tendencia histórica y ranking global.

Expone:
  - tournament_stats(tournament_id, archer_id=None)
      Calcula métricas por arquero en un torneo dado.
      Si archer_id se proporciona, filtra solo ese arquero (aislamiento de datos).
  - archer_trend(archer_id)
      Retorna promedio de puntos por flecha por torneo 'finished' ordenado ASC por fecha.
  - global_ranking()
      Retorna ranking acumulado de todos los arqueros (solo torneos 'finished').

Requerimientos cubiertos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.1, 8.2, 8.3, 8.4,
                          9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from archer.db import get_connection


# ---------------------------------------------------------------------------
# tournament_stats
# ---------------------------------------------------------------------------

def tournament_stats(tournament_id: str, archer_id: str | None = None) -> dict:
    """Calcula estadísticas por arquero para un torneo dado.

    Args:
        tournament_id: UUID del torneo.
        archer_id:     Si se suministra, filtra el resultado a ese arquero
                       (aislamiento de datos — Req 7.5, 7.7).

    Returns:
        En caso de éxito:
        {
            "tournament_id": str,
            "archers": [
                {
                    "archer_id": str,
                    "name": str,
                    "avg_points_per_arrow": float,   # round(sum/count, 2) o 0.00
                    "top_zone_percentage": float,    # round(count(X|10)/total*100, 2) o 0.00
                    "rounds": [                      # ordenadas ASC por round_number
                        {"round_number": int, "total_points": int},
                        ...
                    ]
                },
                ...
            ]
        }

        En caso de error:
        {"error": "Torneo no encontrado.", "status_code": 404}
    """
    conn = get_connection()

    # Verificar existencia del torneo (Req 7.6)
    cursor = conn.execute(
        "SELECT id FROM tournaments WHERE id = ?",
        (tournament_id,),
    )
    if cursor.fetchone() is None:
        return {"error": "Torneo no encontrado.", "status_code": 404}

    # Obtener arqueros inscritos en el torneo (Req 7.1–7.4)
    # JOIN registrations → archers para obtener los datos del arquero
    if archer_id is not None:
        # Filtrar por archer_id (Req 7.5, 7.7)
        cursor = conn.execute(
            """
            SELECT DISTINCT a.id AS archer_id, a.name
            FROM registrations r
            JOIN archers a ON a.id = r.archer_id
            WHERE r.tournament_id = ?
              AND r.archer_id = ?
            ORDER BY a.name ASC
            """,
            (tournament_id, archer_id),
        )
    else:
        cursor = conn.execute(
            """
            SELECT DISTINCT a.id AS archer_id, a.name
            FROM registrations r
            JOIN archers a ON a.id = r.archer_id
            WHERE r.tournament_id = ?
            ORDER BY a.name ASC
            """,
            (tournament_id,),
        )

    enrolled = cursor.fetchall()

    archers_stats = []

    for row in enrolled:
        a_id = row["archer_id"]
        a_name = row["name"]

        # --- Métricas agregadas (Req 7.1, 7.2) ---
        agg_cursor = conn.execute(
            """
            SELECT
                COUNT(*)                                          AS total_arrows,
                COALESCE(SUM(points), 0)                         AS total_points,
                SUM(CASE WHEN arrow_val IN ('X', '10') THEN 1 ELSE 0 END) AS top_zone_count
            FROM scores
            WHERE archer_id = ?
              AND tournament_id = ?
            """,
            (a_id, tournament_id),
        )
        agg = agg_cursor.fetchone()

        total_arrows = agg["total_arrows"]
        total_points = agg["total_points"]
        top_zone_count = agg["top_zone_count"]

        if total_arrows > 0:
            avg_points_per_arrow = round(total_points / total_arrows, 2)
            top_zone_percentage = round(top_zone_count / total_arrows * 100, 2)
        else:
            # Req 7.4 — arquero sin flechas: métricas en 0.00
            avg_points_per_arrow = 0.00
            top_zone_percentage = 0.00

        # --- Serie de rondas (Req 7.3) ---
        rounds_cursor = conn.execute(
            """
            SELECT round_number, SUM(points) AS total_points
            FROM scores
            WHERE archer_id = ?
              AND tournament_id = ?
            GROUP BY round_number
            ORDER BY round_number ASC
            """,
            (a_id, tournament_id),
        )
        rounds = [
            {"round_number": r["round_number"], "total_points": r["total_points"]}
            for r in rounds_cursor.fetchall()
        ]

        archers_stats.append(
            {
                "archer_id": a_id,
                "name": a_name,
                "avg_points_per_arrow": avg_points_per_arrow,
                "top_zone_percentage": top_zone_percentage,
                "rounds": rounds,
            }
        )

    return {
        "tournament_id": tournament_id,
        "archers": archers_stats,
    }


# ---------------------------------------------------------------------------
# archer_trend
# ---------------------------------------------------------------------------

def archer_trend(archer_id: str) -> list[dict]:
    """Retorna la tendencia histórica del arquero a lo largo de torneos 'finished'.

    Para cada torneo 'finished' en que el arquero estuvo inscrito calcula el
    promedio de puntos por flecha (round(sum/count, 2)).  Si el arquero no
    registró ninguna flecha en ese torneo el promedio es 0.00 (Req 8.4).

    Los resultados se ordenan de forma ascendente por la fecha del torneo
    (Req 8.1).

    Args:
        archer_id: UUID del arquero.

    Returns:
        Lista de objetos JSON ordenada ASC por fecha:
        [
            {
                "tournament_name": str,
                "date": str,               # "YYYY-MM-DD"
                "avg_points_per_arrow": float
            },
            ...
        ]
        Arreglo vacío si el arquero no participó en torneos 'finished' (Req 8.3).

    Requerimientos: 8.1, 8.2, 8.3, 8.4
    """
    conn = get_connection()

    # Obtener todos los torneos 'finished' en los que el arquero está inscrito,
    # junto con el agregado de sus flechas (puede ser 0 si no tiró ninguna).
    # LEFT JOIN con scores permite incluir torneos sin flechas (Req 8.4).
    cursor = conn.execute(
        """
        SELECT
            t.name                          AS tournament_name,
            t.date                          AS date,
            COUNT(s.id)                     AS total_arrows,
            COALESCE(SUM(s.points), 0)      AS total_points
        FROM registrations r
        JOIN tournaments t ON t.id = r.tournament_id
        LEFT JOIN scores s
            ON  s.archer_id     = r.archer_id
            AND s.tournament_id = r.tournament_id
        WHERE r.archer_id = ?
          AND t.status    = 'finished'
        GROUP BY t.id, t.name, t.date
        ORDER BY t.date ASC
        """,
        (archer_id,),
    )
    rows = cursor.fetchall()

    if not rows:
        # Req 8.3 — sin torneos finished devuelve arreglo vacío
        return []

    trend = []
    for row in rows:
        total_arrows = row["total_arrows"]
        total_points = row["total_points"]

        if total_arrows > 0:
            avg = round(total_points / total_arrows, 2)
        else:
            # Req 8.4 — torneo sin flechas → promedio 0.00
            avg = 0.00

        trend.append(
            {
                "tournament_name": row["tournament_name"],
                "date": row["date"],
                "avg_points_per_arrow": avg,
            }
        )

    return trend


# ---------------------------------------------------------------------------
# global_ranking
# ---------------------------------------------------------------------------

def global_ranking() -> list[dict]:
    """Retorna el ranking global acumulado de todos los arqueros registrados.

    Solo se contabilizan puntos de torneos con estado 'finished' (Req 9.3).
    Los arqueros sin torneos 'finished' aparecen con totales en cero (Req 9.4).
    El resultado se ordena por total_points DESC y, en empate, name ASC (Req 9.2).

    Returns:
        Lista de dicts con la posición asignada de forma secuencial:
        [
            {
                "position": int,
                "archer_id": str,
                "name": str,
                "total_points": int,
                "avg_points_per_arrow": float,
                "tournaments_played": int
            },
            ...
        ]

    Raises:
        Exception con mensaje 'Servicio no disponible temporalmente' cuando la
        base de datos no está disponible — la capa de rutas la captura y
        retorna HTTP 503 (Req 9.6).

    Requerimientos: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
    """
    try:
        conn = get_connection()
    except Exception as exc:
        raise Exception("Servicio no disponible temporalmente") from exc

    try:
        # Obtener todos los arqueros registrados (Req 9.1, 9.4).
        # LEFT JOIN con registrations + torneos finished para acumular
        # puntos y contar torneos disputados.  Los arqueros sin torneos
        # finished aparecen gracias al LEFT JOIN con NULLs que COALESCE
        # convierte en cero.
        cursor = conn.execute(
            """
            SELECT
                a.id                                      AS archer_id,
                a.name                                    AS name,
                COALESCE(a.photo_url, '')                 AS photo_url,
                COALESCE(SUM(s.points), 0)                AS total_points,
                COUNT(s.id)                               AS total_arrows,
                COUNT(DISTINCT CASE
                    WHEN t.status = 'finished' THEN r.tournament_id
                    ELSE NULL
                END)                                      AS tournaments_played
            FROM archers a
            LEFT JOIN registrations r ON r.archer_id = a.id
            LEFT JOIN tournaments t
                ON  t.id     = r.tournament_id
                AND t.status = 'finished'
            LEFT JOIN scores s
                ON  s.archer_id     = a.id
                AND s.tournament_id = t.id
            GROUP BY a.id, a.name
            ORDER BY total_points DESC, a.name ASC
            """,
        )
        rows = cursor.fetchall()
    except Exception as exc:
        raise Exception("Servicio no disponible temporalmente") from exc

    ranking = []
    for position, row in enumerate(rows, start=1):
        total_points = row["total_points"]
        total_arrows = row["total_arrows"]

        if total_arrows > 0:
            avg = round(total_points / total_arrows, 2)
        else:
            avg = 0.00

        ranking.append(
            {
                "position": position,
                "archer_id": row["archer_id"],
                "name": row["name"],
                "photo_url": row["photo_url"] or "",
                "total_points": total_points,
                "avg_points_per_arrow": avg,
                "tournaments_played": row["tournaments_played"],
            }
        )

    return ranking
