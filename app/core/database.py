from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import ContextManager

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import settings

pool = ConnectionPool(
    conninfo=settings.conninfo,
    open=False,
    min_size=1,
    max_size=5,
    timeout=3,  # Falla rápido si la base no responde, en lugar de dejar colgada la petición.
    check=ConnectionPool.check_connection,  # Descarta conexiones rotas tras reiniciar la base.
)


LOAD_TIMEOUT_SECONDS = 60


def get_connection() -> Iterator[psycopg.Connection]:
    with pool.connection() as connection:
        yield connection


@contextmanager
def _load_connection() -> Iterator[psycopg.Connection]:
    # Las cargas se procesan de a una y pueden hacer fila, así que esperan más que una consulta.
    with pool.connection(timeout=LOAD_TIMEOUT_SECONDS) as connection:
        yield connection


def get_load_connection_opener() -> Callable[[], ContextManager[psycopg.Connection]]:
    """Permite pedir la conexión solo al guardar, y no retenerla mientras se analiza el archivo."""
    return _load_connection
