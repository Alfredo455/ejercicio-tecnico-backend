from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

LOCAL_DAY = "(recorded_at AT TIME ZONE 'America/Santiago')::date"

# Una lectura abre sesión si es la primera del dispositivo o si pasaron MÁS de 10 minutos desde la
# anterior. Se calcula sobre todas sus lecturas: una sesión puede venir del día previo o seguir al
# siguiente, y un dato atrasado puede unir dos sesiones.
SESSIONS_SQL = """
WITH marked AS (
    SELECT recorded_at, lat, lon,
           COALESCE(
               recorded_at - lag(recorded_at) OVER (ORDER BY recorded_at) > interval '10 minutes',
               true
           ) AS starts_session
    FROM readings
    WHERE device_id = %(device_id)s
),
numbered AS (
    SELECT *, count(*) FILTER (WHERE starts_session) OVER (ORDER BY recorded_at) AS session_number
    FROM marked
),
sessions AS (
    SELECT min(recorded_at) AS start_at,
           max(recorded_at) AS end_at,
           count(*) AS readings,
           count(lat) AS positions,
           COALESCE(
               json_agg(json_build_array(lon, lat) ORDER BY recorded_at) FILTER (WHERE lat IS NOT NULL),
               '[]'::json
           ) AS coordinates
    FROM numbered
    GROUP BY session_number
)
SELECT start_at, end_at, readings, positions, coordinates,
       round(extract(epoch FROM end_at - start_at) / 60, 2)::float8 AS duration_min
FROM sessions
WHERE (start_at AT TIME ZONE 'America/Santiago')::date = %(day)s
ORDER BY start_at
"""


def _fetch_all(connection: psycopg.Connection, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, params).fetchall()


def device_exists(connection: psycopg.Connection, device_id: str) -> bool:
    query = "SELECT EXISTS (SELECT 1 FROM readings WHERE device_id = %s)"
    return connection.execute(query, (device_id,)).fetchone()[0]


def list_devices(connection: psycopg.Connection) -> list[dict[str, Any]]:
    return _fetch_all(
        connection,
        """
        SELECT device_id,
               (min(recorded_at) AT TIME ZONE 'America/Santiago')::date AS first_day,
               (max(recorded_at) AT TIME ZONE 'America/Santiago')::date AS last_day
        FROM readings
        GROUP BY device_id
        ORDER BY device_id
        """,
        {},
    )


def get_day_stats(connection: psycopg.Connection, device_id: str, day: date) -> dict[str, Any]:
    return _fetch_all(
        connection,
        f"""
        SELECT count(*) AS readings, round(avg(value), 2)::float8 AS avg_value
        FROM readings
        WHERE device_id = %(device_id)s AND {LOCAL_DAY} = %(day)s
        """,
        {"device_id": device_id, "day": day},
    )[0]


def get_sessions(connection: psycopg.Connection, device_id: str, day: date) -> list[dict[str, Any]]:
    return _fetch_all(connection, SESSIONS_SQL, {"device_id": device_id, "day": day})
