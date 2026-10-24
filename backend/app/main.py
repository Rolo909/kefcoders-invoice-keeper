import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import API_PREFIX
from app.api.v1 import router as api_v1_router
from app.config import get_settings
from app.db import engine, session_factory
from app.errors import register_error_handlers
from app.services.auth import LoginRateLimiter
from app.services.reminders import ReminderDispatcher, build_notifiers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title="Invoice Keeper API",
        version="0.1.0",
        description="Напоминания о регулярных платежах: платежи, периоды оплаты, итоги по валютам, пользователи.",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.login_limiter = LoginRateLimiter()
    app.state.reminders = ReminderDispatcher(
        session_factory,
        build_notifiers(settings),
        remind_days_before=settings.remind_days_before,
        timezone=settings.timezone,
    )
    register_error_handlers(app)
    app.include_router(api_v1_router)
    return app


app = create_app()
