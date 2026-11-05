"""Carga de un archivo CSV, usada por POST /batches y por el comando: python -m app.ingestion.load ruta.csv"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.ingestion.csv_reader import InvalidFile, ParsedFile, parse_csv

# Identifica el candado que procesa un archivo a la vez, para que el orden de llegada sea inequívoco.
LOAD_LOCK_ID = 727_001


@dataclass(frozen=True, slots=True)
class StoreResult:
    already_loaded: bool
    inserted: int = 0
    updated: int = 0


def store_batch(connection: psycopg.Connection, parsed: ParsedFile) -> StoreResult:
    """Guarda el archivo en una sola transacción: ante un error no queda nada parcial."""
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (LOAD_LOCK_ID,))

        # Sin esto, recargar un lote antiguo revertiría lo que corrigió uno posterior.
        already_loaded = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM batches WHERE file_sha256 = %s)", (parsed.sha256,)
        ).fetchone()[0]
        if already_loaded:
            return StoreResult(already_loaded=True)

        batch_id = _insert_batch(connection, parsed)
        return _upsert_readings(connection, batch_id, parsed)


def _insert_batch(connection: psycopg.Connection, parsed: ParsedFile) -> int:
    batch_id = connection.execute(
        """
        INSERT INTO batches (file_name, file_sha256, rows_read, rows_valid, rows_discarded)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (parsed.file_name, parsed.sha256, parsed.rows_read, parsed.rows_valid, parsed.rows_discarded),
    ).fetchone()[0]

    for reason, rows in parsed.rejections.items():
        connection.execute(
            "INSERT INTO batch_rejections (batch_id, reason, rows) VALUES (%s, %s, %s)",
            (batch_id, reason.value, rows),
        )
    return batch_id


def _upsert_readings(connection: psycopg.Connection, batch_id: int, parsed: ParsedFile) -> StoreResult:
    before = connection.execute("SELECT count(*) FROM readings").fetchone()[0]

    # COPY no admite ON CONFLICT: entra primero a una tabla temporal y desde ahí se combina.
    connection.execute("CREATE TEMP TABLE incoming_readings (LIKE readings) ON COMMIT DROP")
    with connection.cursor() as cursor:
        with cursor.copy(
            """
            COPY incoming_readings (device_id, recorded_at, value, lat, lon, batch_id, source_line)
            FROM STDIN
            """
        ) as copy:
            for sourced in parsed.readings.values():
                reading = sourced.reading
                copy.write_row(
                    (
                        reading.device_id,
                        reading.recorded_at,
                        reading.value,
                        reading.lat,
                        reading.lon,
                        batch_id,
                        sourced.source_line,
                    )
                )

    # Reemplaza la fila completa: una lectura nueva sin dato también borra el dato anterior.
    connection.execute(
        """
        INSERT INTO readings (device_id, recorded_at, value, lat, lon, batch_id, source_line)
        SELECT device_id, recorded_at, value, lat, lon, batch_id, source_line
        FROM incoming_readings
        ON CONFLICT (device_id, recorded_at) DO UPDATE
        SET value = EXCLUDED.value,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            batch_id = EXCLUDED.batch_id,
            source_line = EXCLUDED.source_line
        """
    )

    after = connection.execute("SELECT count(*) FROM readings").fetchone()[0]
    inserted = after - before
    return StoreResult(already_loaded=False, inserted=inserted, updated=len(parsed.readings) - inserted)


def load_file(connection: psycopg.Connection, path: Path) -> tuple[ParsedFile, StoreResult]:
    parsed = parse_csv(path.read_bytes(), path.name)
    return parsed, store_batch(connection, parsed)


def format_summary(parsed: ParsedFile, result: StoreResult) -> str:
    status = "ya estaba cargado, sin cambios" if result.already_loaded else "cargado"
    lines = [
        f"Archivo: {parsed.file_name} ({status})",
        f"Filas leídas: {parsed.rows_read}",
        f"Filas válidas: {parsed.rows_valid}",
        f"Filas descartadas: {parsed.rows_discarded}",
    ]
    lines += [f"  {reason.value}: {rows}" for reason, rows in sorted(parsed.rejections.items())]
    if not result.already_loaded:
        lines += [f"Lecturas nuevas: {result.inserted}", f"Lecturas actualizadas: {result.updated}"]
    return "\n".join(lines)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga un archivo CSV de lecturas en PostgreSQL.")
    parser.add_argument("path", type=Path, help="Ruta del archivo CSV")
    path = parser.parse_args(arguments).path

    # Se importa aquí para que el análisis del CSV no necesite la configuración de la base.
    from app.core.config import settings

    try:
        with psycopg.connect(settings.conninfo) as connection:
            parsed, result = load_file(connection, path)
    except OSError as error:
        print(f"No se pudo leer el archivo {path}: {error.strerror}", file=sys.stderr)
        return 1
    except InvalidFile as error:
        print(f"Archivo inválido {path}: {error}", file=sys.stderr)
        return 1
    except psycopg.Error as error:
        print(f"Error de base de datos; no se cargó nada: {error}", file=sys.stderr)
        return 1

    print(format_summary(parsed, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
