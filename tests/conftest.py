"""Las pruebas de integración usan una base aparte, por lo que no tocan los datos cargados."""

from contextlib import contextmanager

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

TEST_DATABASE = "lecturas_test"


@pytest.fixture(scope="session")
def test_conninfo():
    from app.core.config import settings
    from app.core.migrate import SCHEMA_PATH

    with psycopg.connect(settings.conninfo, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DATABASE}")

    conninfo = make_conninfo(settings.conninfo, dbname=TEST_DATABASE)
    with psycopg.connect(conninfo) as connection:
        connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    yield conninfo

    with psycopg.connect(settings.conninfo, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")


@pytest.fixture
def db(test_conninfo):
    with psycopg.connect(test_conninfo, autocommit=True) as connection:
        connection.execute("TRUNCATE readings, batch_rejections, batches RESTART IDENTITY")
        yield connection


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.core.database import get_connection, get_load_connection_opener
    from app.main import app

    @contextmanager
    def open_test_connection():
        yield db

    app.dependency_overrides[get_connection] = lambda: db
    app.dependency_overrides[get_load_connection_opener] = lambda: open_test_connection
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def write_csv(tmp_path):
    """Crea un CSV a partir de filas (device_id, recorded_at, value, lat, lon)."""
    counter = iter(range(1, 1000))

    def _write(*rows, name=None):
        path = tmp_path / (name or f"lote_{next(counter)}.csv")
        lines = ["device_id,recorded_at,value,lat,lon"] + [",".join(row) for row in rows]
        path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        return path

    return _write
