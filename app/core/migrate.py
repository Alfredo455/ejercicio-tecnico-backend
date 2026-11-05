"""Aplica el esquema a la base: python -m app.core.migrate"""

from pathlib import Path

import psycopg

from app.core.config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def apply_schema() -> None:
    with psycopg.connect(settings.conninfo) as connection:
        connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    apply_schema()
    print("Esquema aplicado")
