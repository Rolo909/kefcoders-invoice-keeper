import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionDep

DB_CHECK_TIMEOUT_SECONDS = 2

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Проверка работоспособности API и базы данных",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthOut, "description": "База данных недоступна"}},
)
async def health(session: SessionDep) -> HealthOut | JSONResponse:
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.warning("Health check: база данных недоступна", exc_info=True)
        body = HealthOut(status="degraded", db="error")
        return JSONResponse(body.model_dump(), status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return HealthOut(status="ok", db="ok")
