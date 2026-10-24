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

API_DESCRIPTION = """
Напоминания о регулярных платежах: аренда, подписки, серверы.

**Авторизация.** `POST /api/v1/auth/login` → скопируйте `access_token` → кнопка **Authorize**.
Веб-панель использует тот же вход, токен хранится в HttpOnly-cookie.

**Роли.** Администратор (задаётся в `.env`) управляет платежами и пользователями.
Пользователь видит платежи, отмечает оплату и исправляет фактическую дату.

**Ошибки** — всегда `{"detail": "текст для пользователя", "code": "машинный код"}`.
""".strip()

OPENAPI_TAGS = [
    {"name": "auth", "description": "Вход, текущий пользователь, выход"},
    {"name": "recurring-payments", "description": "Регулярные платежи (создают и прекращают только администраторы)"},
    {"name": "payment-occurrences", "description": "Периоды платежей: срок, отметка «Оплачено», фактическая дата"},
    {"name": "payments", "description": "Итоги по валютам — отдельно RUB, USD и EUR, без конвертации"},
    {"name": "budgets", "description": "Бюджеты по валютам на месяц и год (задаёт администратор)"},
    {"name": "users", "description": "Обычные пользователи (только для администратора)"},
    {"name": "attachments", "description": "Чек (файл) или ссылка к конкретной оплате"},
    {"name": "logs", "description": "Журнал входов и действий, журнал напоминаний (администратор)"},
    {"name": "telegram", "description": "Привязка Telegram для кнопки «Оплачено» в напоминаниях"},
    {"name": "health", "description": "Проверка работоспособности"},
]


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
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
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
