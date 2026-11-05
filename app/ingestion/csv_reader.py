"""Interpreta el contenido de un CSV en memoria, sin tocar el archivo ni la base de datos."""

import csv
import hashlib
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.ingestion.validation import COLUMNS, InvalidRow, Reading, RejectReason, parse_row


class InvalidFile(ValueError):
    """El archivo completo no se puede interpretar, a diferencia de una fila inválida."""


@dataclass(frozen=True, slots=True)
class SourcedReading:
    reading: Reading
    source_line: int


@dataclass(slots=True)
class ParsedFile:
    file_name: str
    sha256: str
    rows_read: int = 0
    rows_valid: int = 0
    rejections: Counter[RejectReason] = field(default_factory=Counter)
    # Una entrada por dispositivo e instante: la fila más abajo sobrescribe a las anteriores.
    readings: dict[tuple[str, datetime], SourcedReading] = field(default_factory=dict)

    @property
    def rows_discarded(self) -> int:
        return sum(self.rejections.values())


def parse_csv(content: bytes, file_name: str) -> ParsedFile:
    parsed = ParsedFile(file_name=file_name, sha256=hashlib.sha256(content).hexdigest())

    if b"\x00" in content:  # PostgreSQL no admite este carácter en campos de texto.
        raise InvalidFile("El archivo contiene caracteres nulos")

    try:
        text = content.decode("utf-8-sig")  # utf-8-sig también tolera un BOM al inicio.
    except UnicodeDecodeError as error:
        raise InvalidFile("El archivo no está codificado en UTF-8") from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise InvalidFile(f"Faltan columnas en el encabezado: {', '.join(missing)}")

    try:
        for row in reader:
            parsed.rows_read += 1
            try:
                reading = parse_row(row)
            except InvalidRow as error:
                parsed.rejections[error.reason] += 1
                continue
            parsed.rows_valid += 1
            key = (reading.device_id, reading.recorded_at)
            parsed.readings[key] = SourcedReading(reading, reader.line_num)
    except csv.Error as error:
        raise InvalidFile(f"CSV mal formado en la línea {reader.line_num}: {error}") from error

    return parsed
