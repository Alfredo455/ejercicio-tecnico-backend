from collections.abc import Callable
from pathlib import PurePath
from typing import Annotated, Any, ContextManager

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.schemas import BatchResult, ErrorResponse
from app.core.database import get_load_connection_opener
from app.ingestion.csv_reader import InvalidFile, parse_csv
from app.ingestion.load import store_batch

router = APIRouter(prefix="/batches", tags=["batches"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post(
    "",
    response_model=BatchResult,
    responses={
        413: {"model": ErrorResponse, "description": "El archivo supera los 50 MB"},
        422: {"model": ErrorResponse, "description": "El archivo no se puede interpretar; no se cargó nada"},
        503: {"model": ErrorResponse, "description": "Base de datos no disponible"},
    },
    summary="Cargar un archivo CSV",
    description=(
        "Es idempotente: un archivo con contenido ya cargado responde `200` con `already_loaded: true` "
        "y no cambia nada, incluso si se envía varias veces a la vez. Carga un solo archivo por petición, "
        "en el campo `file` de un formulario `multipart/form-data`, y en el orden en que llegaron: "
        "entre archivos distintos, vale el que se carga después."
    ),
)
def upload_batch(
    file: Annotated[UploadFile, File(description="Archivo CSV de lecturas")],
    open_connection: Annotated[Callable[[], ContextManager[psycopg.Connection]], Depends(get_load_connection_opener)],
) -> dict[str, Any]:
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera los 50 MB")

    file_name = PurePath(file.filename or "sin_nombre.csv").name
    try:
        parsed = parse_csv(content, file_name)
        with open_connection() as connection:
            result = store_batch(connection, parsed)
    except InvalidFile as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.DataError as error:  # Por ejemplo, un valor demasiado grande para PostgreSQL.
        raise HTTPException(status_code=422, detail="El archivo tiene datos que no se pueden guardar") from error

    return {
        "file_name": parsed.file_name,
        "already_loaded": result.already_loaded,
        "rows_read": parsed.rows_read,
        "rows_valid": parsed.rows_valid,
        "rows_discarded": parsed.rows_discarded,
        "rejections": {reason.value: rows for reason, rows in sorted(parsed.rejections.items())},
        "inserted": result.inserted,
        "updated": result.updated,
    }
