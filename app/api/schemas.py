from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Dispositivo no encontrado: D-9999"])


class BatchResult(BaseModel):
    file_name: str = Field(examples=["lote_1.csv"])
    already_loaded: bool = Field(description="true si este contenido ya se había cargado; no se cambió nada")
    rows_read: int = Field(description="Filas leídas del archivo")
    rows_valid: int = Field(description="Filas válidas, incluidas las repetidas dentro del archivo")
    rows_discarded: int = Field(description="Filas descartadas")
    rejections: dict[str, int] = Field(
        description="Filas descartadas por motivo",
        examples=[{"device_id_vacio": 47, "fecha_invalida": 48, "fecha_sin_zona_horaria": 107}],
    )
    inserted: int = Field(description="Lecturas nuevas; 0 si el archivo ya estaba cargado")
    updated: int = Field(description="Lecturas reemplazadas; 0 si el archivo ya estaba cargado")


class Device(BaseModel):
    device_id: str = Field(examples=["D-0001"])
    first_day: Date = Field(description="Día de la primera lectura, en hora de America/Santiago")
    last_day: Date = Field(description="Día de la última lectura, en hora de America/Santiago")


class Session(BaseModel):
    start: str = Field(description="Inicio en ISO-8601 con offset", examples=["2026-09-05T10:15:02-04:00"])
    end: str = Field(description="Fin en ISO-8601 con offset", examples=["2026-09-05T12:01:40-04:00"])
    readings: int = Field(description="Lecturas de la sesión completa, aunque termine otro día")
    duration_min: float = Field(description="Duración en minutos, con 2 decimales", examples=[106.63])


class DaySummary(BaseModel):
    device_id: str = Field(examples=["D-0001"])
    date: Date
    readings: int = Field(description="Lecturas cuyo instante cae en este día")
    avg_value: float | None = Field(description="Promedio con 2 decimales; null si no hay valores", examples=[51.23])
    sessions: list[Session] = Field(description="Sesiones que comienzan este día, ordenadas por inicio")


class LineString(BaseModel):
    type: Literal["LineString"]
    coordinates: list[list[float]] = Field(description="Puntos [lon, lat] ordenados por instante")


class Point(BaseModel):
    type: Literal["Point"]
    coordinates: list[float] = Field(description="Punto [lon, lat]")


class TrackProperties(BaseModel):
    start: str = Field(examples=["2026-09-05T10:15:02-04:00"])
    end: str = Field(examples=["2026-09-05T12:01:40-04:00"])
    readings: int = Field(description="Lecturas de la sesión completa")
    positions: int = Field(description="Puntos de la sesión con posición")


class TrackFeature(BaseModel):
    type: Literal["Feature"]
    geometry: LineString | Point | None = Field(description="LineString con 2 o más puntos, Point con 1, null con 0")
    properties: TrackProperties


class DayTrack(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[TrackFeature] = Field(description="Un Feature por sesión, en el mismo orden que el resumen")
