from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1 import (
    attachments,
    auth,
    budgets,
    calendar,
    calendar_feed,
    health,
    inbox,
    logs,
    occurrences,
    payments_summary,
    recurring_payments,
    telegram,
    users,
)

API_PREFIX = "/api/v1"

# Публичные маршруты — вход, проверка работоспособности и файл календаря (.ics, по секрету в ссылке).
public_router = APIRouter()
public_router.include_router(health.router)
public_router.include_router(auth.public_router)
public_router.include_router(calendar_feed.public_router)

# Всё остальное недоступно без авторизации — проверка на уровне роутера, а не каждого эндпоинта.
protected_router = APIRouter(dependencies=[Depends(get_current_user)])
protected_router.include_router(auth.router)
protected_router.include_router(recurring_payments.router)
protected_router.include_router(occurrences.router)
protected_router.include_router(payments_summary.router)
protected_router.include_router(calendar.router)
protected_router.include_router(budgets.router)
protected_router.include_router(attachments.router)
protected_router.include_router(logs.router)
protected_router.include_router(inbox.router)
protected_router.include_router(users.router)
protected_router.include_router(telegram.router)
protected_router.include_router(calendar_feed.router)

router = APIRouter(prefix=API_PREFIX)
router.include_router(public_router)
router.include_router(protected_router)
