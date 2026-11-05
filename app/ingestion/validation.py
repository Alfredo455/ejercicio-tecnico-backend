"""Convierte una fila del CSV en una lectura normalizada o la rechaza con un motivo.

Son funciones puras: no leen archivos ni usan la base de datos.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

COLUMNS = ("device_id", "recorded_at", "value", "lat", "lon")


class RejectReason(StrEnum):
    WRONG_COLUMNS = "columnas_incorrectas"
    EMPTY_DEVICE_ID = "device_id_vacio"
    INVALID_DATE = "fecha_invalida"
    MISSING_TIMEZONE = "fecha_sin_zona_horaria"
    INVALID_VALUE = "value_no_numerico"


class InvalidRow(ValueError):
    def __init__(self, reason: RejectReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Reading:
    device_id: str
    recorded_at: datetime  # Siempre en UTC: el mismo instante da la misma clave con cualquier offset.
    value: Decimal | None  # None: sin dato.
    lat: float | None  # lat y lon en None: sin posición.
    lon: float | None


def normalize_device_id(text: str) -> str:
    return text.strip().upper()


def parse_device_id(text: str) -> str:
    device_id = normalize_device_id(text)
    if not device_id:
        raise InvalidRow(RejectReason.EMPTY_DEVICE_ID)
    return device_id


def parse_recorded_at(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError as error:
        raise InvalidRow(RejectReason.INVALID_DATE) from error

    if moment.utcoffset() is None:
        raise InvalidRow(RejectReason.MISSING_TIMEZONE)

    try:
        return moment.astimezone(UTC)
    except OverflowError as error:  # Fechas en el límite del calendario, como el año 1 con offset.
        raise InvalidRow(RejectReason.INVALID_DATE) from error


def parse_value(text: str) -> Decimal | None:
    cleaned = text.strip()
    if not cleaned or cleaned.casefold() == "nan":
        return None

    try:
        value = Decimal(cleaned)
    except InvalidOperation as error:
        raise InvalidRow(RejectReason.INVALID_VALUE) from error

    if not value.is_finite():  # Infinity no es "sin dato" según las reglas: la fila es inválida.
        raise InvalidRow(RejectReason.INVALID_VALUE)
    return value


def parse_position(lat_text: str, lon_text: str) -> tuple[float, float] | tuple[None, None]:
    """Una posición inutilizable nunca invalida la fila: solo la deja sin posición."""
    try:
        lat, lon = float(lat_text), float(lon_text)
    except ValueError:
        return None, None

    # Las comparaciones con NaN son falsas, así que NaN también cae fuera de rango.
    in_range = -90 <= lat <= 90 and -180 <= lon <= 180
    if not in_range or (lat == 0 and lon == 0):
        return None, None
    return lat, lon


def parse_row(row: Mapping[str | None, str | None]) -> Reading:
    """Recibe una fila de csv.DictReader, que usa None para columnas faltantes o sobrantes."""
    if None in row or any(row.get(column) is None for column in COLUMNS):
        raise InvalidRow(RejectReason.WRONG_COLUMNS)

    lat, lon = parse_position(row["lat"], row["lon"])
    return Reading(
        device_id=parse_device_id(row["device_id"]),
        recorded_at=parse_recorded_at(row["recorded_at"]),
        value=parse_value(row["value"]),
        lat=lat,
        lon=lon,
    )
