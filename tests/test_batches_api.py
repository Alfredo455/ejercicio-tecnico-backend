from concurrent.futures import ThreadPoolExecutor

import psycopg

from app.api import batches
from app.ingestion import load as load_module

HEADER = "device_id,recorded_at,value,lat,lon\n"
ROW = "D-0001,2026-09-05T14:00:00Z,10,-33.4,-70.6\n"


def upload(client, content, name="lote.csv"):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return client.post("/batches", files={"file": (name, content, "text/csv")})


def test_upload_loads_the_file_and_reports_every_count(client):
    response = upload(client, HEADER + ROW + ",2026-09-05T14:00:00Z,1,,\n" + "D-0001,ayer,1,,\n")

    assert response.status_code == 200
    assert response.json() == {
        "file_name": "lote.csv",
        "already_loaded": False,
        "rows_read": 3,
        "rows_valid": 1,
        "rows_discarded": 2,
        "rejections": {"device_id_vacio": 1, "fecha_invalida": 1},
        "inserted": 1,
        "updated": 0,
    }
    assert client.get("/devices/D-0001/days/2026-09-05").json()["readings"] == 1


def test_uploading_the_same_content_again_changes_nothing(client, db):
    upload(client, HEADER + ROW)

    response = upload(client, HEADER + ROW, name="otro_nombre.csv")

    body = response.json()
    assert response.status_code == 200
    assert body["already_loaded"] is True
    assert (body["rows_read"], body["inserted"], body["updated"]) == (1, 0, 0)
    assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 1


def test_later_upload_replaces_and_reuploading_the_old_one_does_not_revert(client, db):
    first = HEADER + ROW
    upload(client, first)
    body = upload(client, HEADER + "D-0001,2026-09-05T10:00:00-04:00,20,-33.4,-70.6\n").json()
    assert (body["inserted"], body["updated"]) == (0, 1)

    upload(client, first)

    assert client.get("/devices/D-0001/days/2026-09-05").json()["avg_value"] == 20.0


def test_simultaneous_uploads_of_the_same_file_apply_it_once(client, db, test_conninfo):
    from fastapi.testclient import TestClient
    from psycopg_pool import ConnectionPool

    from app.core.database import get_load_connection_opener
    from app.main import app

    content = HEADER + ROW

    # Cada petición usa su propia conexión, como en producción, para que el candado actúe de verdad.
    with ConnectionPool(test_conninfo, min_size=1, max_size=4, timeout=30) as pool:
        app.dependency_overrides[get_load_connection_opener] = lambda: pool.connection
        with ThreadPoolExecutor(4) as executor:
            responses = list(executor.map(lambda _: upload(TestClient(app), content), range(4)))

    assert [response.status_code for response in responses] == [200] * 4
    assert sum(not response.json()["already_loaded"] for response in responses) == 1
    assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM readings").fetchone()[0] == 1


def test_path_is_removed_from_the_file_name(client, db):
    assert upload(client, HEADER + ROW, name="../../secreto/lote.csv").json()["file_name"] == "lote.csv"


def test_file_without_the_columns_is_422_and_loads_nothing(client, db):
    response = upload(client, "a,b\n1,2\n")

    assert response.status_code == 422
    assert "Faltan columnas" in response.json()["detail"]
    assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 0


def test_binary_file_is_422(client):
    assert upload(client, b"\xff\xfe\x00\x01").status_code == 422


def test_empty_file_is_422(client):
    assert upload(client, b"").status_code == 422


def test_value_too_large_for_postgres_is_422_and_loads_nothing(client, db):
    response = upload(client, HEADER + "D-0001,2026-09-05T14:00:00Z,1e999999,,\n")

    assert response.status_code == 422
    assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 0


def test_missing_file_field_is_422(client):
    assert client.post("/batches").status_code == 422


def test_file_over_the_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(batches, "MAX_UPLOAD_BYTES", 10)

    assert upload(client, HEADER + ROW).status_code == 413


def test_failure_in_the_middle_loads_nothing(client, db, monkeypatch):
    def unavailable(*_):
        raise psycopg.OperationalError("conexión perdida")

    monkeypatch.setattr(load_module, "_upsert_readings", unavailable)

    response = upload(client, HEADER + ROW)

    assert response.status_code == 503
    assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 0


def test_preflight_allows_post_from_the_configured_frontend(client):
    from app.core.config import settings

    origin = settings.cors_origin_list[0]

    response = client.options(
        "/batches",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
