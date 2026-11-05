from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from app.ingestion.validation import normalize_device_id
from app.repositories import readings as repository

SANTIAGO = ZoneInfo("America/Santiago")


class DeviceNotFound(Exception):
    def __init__(self, device_id: str) -> None:
        super().__init__(device_id)
        self.device_id = device_id


def _local_iso(moment: datetime) -> str:
    """Usa el offset vigente en ese instante: -04:00 o -03:00 según el horario de Chile."""
    return moment.astimezone(SANTIAGO).isoformat()


def _existing_device_id(connection: psycopg.Connection, device_id: str) -> str:
    normalized = normalize_device_id(device_id)
    if not repository.device_exists(connection, normalized):
        raise DeviceNotFound(normalized)
    return normalized


def list_devices(connection: psycopg.Connection) -> list[dict[str, Any]]:
    return repository.list_devices(connection)


def get_day_summary(connection: psycopg.Connection, device_id: str, day: date) -> dict[str, Any]:
    normalized = _existing_device_id(connection, device_id)
    stats = repository.get_day_stats(connection, normalized, day)
    sessions = repository.get_sessions(connection, normalized, day)
    return {
        "device_id": normalized,
        "date": day,
        "readings": stats["readings"],
        "avg_value": stats["avg_value"],
        "sessions": [
            {
                "start": _local_iso(session["start_at"]),
                "end": _local_iso(session["end_at"]),
                "readings": session["readings"],
                "duration_min": session["duration_min"],
            }
            for session in sessions
        ],
    }


def _geometry(coordinates: list[list[float]]) -> dict[str, Any] | None:
    if not coordinates:
        return None
    if len(coordinates) == 1:
        return {"type": "Point", "coordinates": coordinates[0]}
    return {"type": "LineString", "coordinates": coordinates}


def get_day_track(connection: psycopg.Connection, device_id: str, day: date) -> dict[str, Any]:
    normalized = _existing_device_id(connection, device_id)
    sessions = repository.get_sessions(connection, normalized, day)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _geometry(session["coordinates"]),
                "properties": {
                    "start": _local_iso(session["start_at"]),
                    "end": _local_iso(session["end_at"]),
                    "readings": session["readings"],
                    "positions": session["positions"],
                },
            }
            for session in sessions
        ],
    }
