from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends

from app.core.database import get_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health(connection: Annotated[psycopg.Connection, Depends(get_connection)]) -> dict[str, str]:
    connection.execute("SELECT 1")
    return {"status": "ok", "database": "ok"}
