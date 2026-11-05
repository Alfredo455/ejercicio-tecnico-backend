import re
from datetime import date
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParameter

from app.api.schemas import DaySummary, DayTrack, Device, ErrorResponse
from app.core.database import get_connection
from app.services import devices as service

router = APIRouter(prefix="/devices", tags=["devices"])

Connection = Annotated[psycopg.Connection, Depends(get_connection)]
DeviceId = Annotated[
    str,
    PathParameter(description="No distingue mayúsculas de minúsculas", examples=["D-0001"]),
]

DAY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorResponse, "description": "Base de datos no disponible"},
}
DAY_ERRORS: dict[int | str, dict[str, Any]] = {
    **COMMON_ERRORS,
    404: {"model": ErrorResponse, "description": "Dispositivo inexistente"},
    422: {"model": ErrorResponse, "description": "Fecha con formato inválido o imposible"},
}


def parse_day(
    day: Annotated[
        str,
        PathParameter(description="Día en hora de America/Santiago, con formato YYYY-MM-DD", examples=["2026-09-05"]),
    ],
) -> date:
    try:
        if not DAY_PATTERN.fullmatch(day):
            raise ValueError
        return date.fromisoformat(day)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Fecha inválida: {day}. Usa YYYY-MM-DD") from error


Day = Annotated[date, Depends(parse_day)]


@router.get(
    "",
    response_model=list[Device],
    responses=COMMON_ERRORS,
    summary="Listar dispositivos",
    description="Dispositivos con datos, ordenados por `device_id`.",
)
def list_devices(connection: Connection) -> list[dict[str, Any]]:
    return service.list_devices(connection)


@router.get(
    "/{device_id}/days/{day}",
    response_model=DaySummary,
    responses=DAY_ERRORS,
    summary="Obtener el resumen de un día",
    description=(
        "`readings` y `avg_value` usan las lecturas que caen en el día. `sessions` incluye las sesiones "
        "que comienzan ese día, aunque terminen al siguiente, por lo que sus lecturas pueden no sumar "
        "`readings`. Un día sin lecturas responde `200` con `readings: 0`, `avg_value: null` y `sessions: []`."
    ),
)
def get_day_summary(device_id: DeviceId, day: Day, connection: Connection) -> dict[str, Any]:
    return service.get_day_summary(connection, device_id, day)


@router.get(
    "/{device_id}/days/{day}/track",
    response_model=DayTrack,
    responses=DAY_ERRORS,
    summary="Obtener el recorrido de un día en GeoJSON",
    description=(
        "Un `Feature` por sesión, con las mismas sesiones y en el mismo orden que el resumen. "
        "`coordinates` usa el orden `[lon, lat]`; `geometry` es `LineString`, `Point` o `null` "
        "según la sesión tenga 2 o más puntos, 1 o ninguno."
    ),
)
def get_day_track(device_id: DeviceId, day: Day, connection: Connection) -> dict[str, Any]:
    return service.get_day_track(connection, device_id, day)
