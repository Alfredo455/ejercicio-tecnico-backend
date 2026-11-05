from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import batches, devices, health
from app.core.config import settings
from app.core.database import pool
from app.services.devices import DeviceNotFound


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # wait=False: el pool se conecta en segundo plano; si la base cae, las peticiones responden 503.
    pool.open(wait=False)
    yield
    pool.close()


app = FastAPI(
    title="Servicio de lecturas",
    description=(
        "Carga de archivos CSV, resumen diario y recorrido de los dispositivos. "
        "Los días se calculan en hora de America/Santiago."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(psycopg.OperationalError)
def database_unavailable(_: Request, __: psycopg.OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible"})


@app.exception_handler(DeviceNotFound)
def device_not_found(_: Request, error: DeviceNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"Dispositivo no encontrado: {error.device_id}"})


app.include_router(health.router)
app.include_router(batches.router)
app.include_router(devices.router)
