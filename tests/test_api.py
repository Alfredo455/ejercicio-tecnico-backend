import psycopg

from app.ingestion.load import load_file

BASE_DAY = "/devices/D-0001/days/2026-09-05"


def row(moment, value="10", lat="-33.4", lon="-70.6", device="D-0001"):
    return (device, moment, value, lat, lon)


def test_devices_are_sorted_with_days_in_santiago_time(client, db, write_csv):
    load_file(
        db,
        write_csv(
            # 01:00Z del 5 de septiembre todavía es el día 4 en Santiago.
            row("2026-09-05T01:00:00Z", device="D-0002"),
            row("2026-09-08T12:00:00Z", device="D-0002"),
            row("2026-09-05T12:00:00Z", device="d-0001"),
        ),
    )

    response = client.get("/devices")

    assert response.status_code == 200
    assert response.json() == [
        {"device_id": "D-0001", "first_day": "2026-09-05", "last_day": "2026-09-05"},
        {"device_id": "D-0002", "first_day": "2026-09-04", "last_day": "2026-09-08"},
    ]


def test_devices_is_empty_without_data(client):
    assert client.get("/devices").json() == []


def test_summary_has_the_exact_format(client, db, write_csv):
    load_file(
        db,
        write_csv(
            row("2026-09-05T14:15:02Z", value="50"),
            row("2026-09-05T14:20:02Z", value="52.46"),
        ),
    )

    assert client.get(BASE_DAY).json() == {
        "device_id": "D-0001",
        "date": "2026-09-05",
        "readings": 2,
        "avg_value": 51.23,
        "sessions": [
            {
                "start": "2026-09-05T10:15:02-04:00",
                "end": "2026-09-05T10:20:02-04:00",
                "readings": 2,
                "duration_min": 5.0,
            }
        ],
    }


def test_device_id_is_case_insensitive_in_the_url(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z")))

    assert client.get("/devices/d-0001/days/2026-09-05").json()["device_id"] == "D-0001"


def test_average_ignores_readings_without_data(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z", value="10"), row("2026-09-05T14:01:00Z", value="NaN")))

    body = client.get(BASE_DAY).json()

    assert (body["readings"], body["avg_value"]) == (2, 10.0)


def test_average_is_null_when_no_reading_has_data(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z", value="")))

    body = client.get(BASE_DAY).json()

    assert (body["readings"], body["avg_value"]) == (1, None)


def test_exactly_ten_minutes_stays_in_the_session(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z"), row("2026-09-05T14:10:00Z")))

    assert len(client.get(BASE_DAY).json()["sessions"]) == 1


def test_more_than_ten_minutes_starts_a_new_session(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z"), row("2026-09-05T14:10:01Z")))

    assert len(client.get(BASE_DAY).json()["sessions"]) == 2


def test_rows_out_of_order_are_sorted_by_instant(client, db, write_csv):
    load_file(
        db,
        write_csv(
            row("2026-09-05T14:16:00Z"),
            row("2026-09-05T14:00:00Z"),
            row("2026-09-05T14:08:00Z"),
        ),
    )

    sessions = client.get(BASE_DAY).json()["sessions"]

    assert len(sessions) == 1
    assert sessions[0]["duration_min"] == 16.0


def test_late_reading_joins_two_sessions(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z"), row("2026-09-05T14:16:00Z")))
    assert len(client.get(BASE_DAY).json()["sessions"]) == 2

    load_file(db, write_csv(row("2026-09-05T14:08:00Z")))

    assert len(client.get(BASE_DAY).json()["sessions"]) == 1


def test_session_crossing_midnight_belongs_to_the_day_it_starts(client, db, write_csv):
    load_file(
        db,
        write_csv(
            row("2026-09-05T03:55:00Z"),  # 23:55 del día 4 en Santiago.
            row("2026-09-05T04:05:00Z"),  # 00:05 del día 5 en Santiago.
        ),
    )

    day_4 = client.get("/devices/D-0001/days/2026-09-04").json()
    day_5 = client.get("/devices/D-0001/days/2026-09-05").json()

    assert day_4["readings"] == 1
    assert day_4["sessions"][0]["readings"] == 2
    assert day_4["sessions"][0]["end"] == "2026-09-05T00:05:00-04:00"
    assert day_5["readings"] == 1
    assert day_5["sessions"] == []


def test_daylight_saving_change_uses_the_offset_of_each_instant(client, db, write_csv):
    # El 6 de septiembre de 2026 Chile pasa de las 00:00 a las 01:00: ese día no existe la medianoche.
    load_file(
        db,
        write_csv(
            row("2026-09-06T03:55:00Z"),  # 23:55 -04:00 del día 5.
            row("2026-09-06T04:05:00Z"),  # 01:05 -03:00 del día 6.
        ),
    )

    day_5 = client.get("/devices/D-0001/days/2026-09-05").json()
    day_6 = client.get("/devices/D-0001/days/2026-09-06").json()

    session = day_5["sessions"][0]
    assert session["start"] == "2026-09-05T23:55:00-04:00"
    assert session["end"] == "2026-09-06T01:05:00-03:00"
    assert session["duration_min"] == 10.0
    assert (day_5["readings"], day_6["readings"]) == (1, 1)


def test_existing_device_without_readings_that_day(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z")))

    assert client.get("/devices/D-0001/days/2026-09-10").json() == {
        "device_id": "D-0001",
        "date": "2026-09-10",
        "readings": 0,
        "avg_value": None,
        "sessions": [],
    }


def test_unknown_device_is_404_on_both_endpoints(client):
    assert client.get("/devices/NOPE/days/2026-09-05").status_code == 404
    assert client.get("/devices/NOPE/days/2026-09-05/track").status_code == 404


def test_invalid_day_is_422(client):
    for day in ("2026-02-30", "05-09-2026", "20260905", "1700000000", "ayer"):
        assert client.get(f"/devices/D-0001/days/{day}").status_code == 422
        assert client.get(f"/devices/D-0001/days/{day}/track").status_code == 422


def test_track_has_one_feature_per_session_with_the_right_geometry(client, db, write_csv):
    load_file(
        db,
        write_csv(
            # Sesión 1: dos puntos y una lectura sin posición.
            row("2026-09-05T14:01:00Z", lat="-33.2", lon="-70.2"),
            row("2026-09-05T14:00:00Z", lat="-33.1", lon="-70.1"),
            row("2026-09-05T14:02:00Z", lat="0", lon="0"),
            # Sesión 2: un punto.
            row("2026-09-05T15:00:00Z", lat="-33.3", lon="-70.3"),
            # Sesión 3: sin puntos.
            row("2026-09-05T16:00:00Z", lat="", lon=""),
        ),
    )

    body = client.get(f"{BASE_DAY}/track").json()
    features = body["features"]

    assert body["type"] == "FeatureCollection"
    assert [feature["type"] for feature in features] == ["Feature"] * 3
    assert features[0]["geometry"] == {
        "type": "LineString",
        "coordinates": [[-70.1, -33.1], [-70.2, -33.2]],
    }
    assert features[0]["properties"] == {
        "start": "2026-09-05T10:00:00-04:00",
        "end": "2026-09-05T10:02:00-04:00",
        "readings": 3,
        "positions": 2,
    }
    assert features[1]["geometry"] == {"type": "Point", "coordinates": [-70.3, -33.3]}
    assert features[1]["properties"]["positions"] == 1
    assert features[2]["geometry"] is None
    assert features[2]["properties"]["positions"] == 0


def test_track_has_the_same_sessions_as_the_summary(client, db, write_csv):
    load_file(
        db,
        write_csv(row("2026-09-05T14:00:00Z"), row("2026-09-05T15:00:00Z"), row("2026-09-05T16:00:00Z")),
    )

    sessions = client.get(BASE_DAY).json()["sessions"]
    features = client.get(f"{BASE_DAY}/track").json()["features"]

    assert [(s["start"], s["end"], s["readings"]) for s in sessions] == [
        (f["properties"]["start"], f["properties"]["end"], f["properties"]["readings"]) for f in features
    ]


def test_track_of_a_day_without_sessions_is_empty(client, db, write_csv):
    load_file(db, write_csv(row("2026-09-05T14:00:00Z")))

    assert client.get("/devices/D-0001/days/2026-09-10/track").json() == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_database_down_is_503(client):
    from app.core.database import get_connection
    from app.main import app

    def unavailable():
        raise psycopg.OperationalError("base caída")

    app.dependency_overrides[get_connection] = unavailable

    response = client.get("/devices")

    assert response.status_code == 503
    assert response.json() == {"detail": "Base de datos no disponible"}
