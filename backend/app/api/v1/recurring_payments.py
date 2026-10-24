import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, status

from app.api.deps import (
    ActorScopeDep,
    AdminUser,
    RemindersDep,
    SettingsDep,
    TeamScopeDep,
    TodayDep,
    client_ip,
    utc_now,
)
from app.api.v1.presenters import payment_detail_out, payment_out
from app.db import SessionDep
from app.domain.enums import Currency
from app.schemas.common import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery, Page
from app.schemas.payment import RecurringPaymentCreate, RecurringPaymentDetailOut, RecurringPaymentOut
from app.services import payments as payments_service
from app.services.occurrences import ensure_occurrences

router = APIRouter(prefix="/recurring-payments", tags=["recurring-payments"])

_NOT_FOUND: dict[int | str, dict[str, str]] = {status.HTTP_404_NOT_FOUND: {"description": "Платёж не найден"}}


@router.get("", response_model=Page[RecurringPaymentOut], summary="Получение списка регулярных платежей")
async def list_payments(
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    scope: TeamScopeDep,
    include_deleted: Annotated[bool, Query(description="Показать и прекращённые платежи")] = False,
    currency: Currency | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Поиск по названию")] = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
) -> Page[RecurringPaymentOut]:
    await ensure_occurrences(session, today=today, horizon_days=settings.occurrence_horizon_days)
    await session.commit()
    views = await payments_service.list_payments(
        session, include_deleted=include_deleted, currency=currency, query=q, today=today, scope=scope
    )
    items = [payment_out(v, today=today, remind_days_before=settings.remind_days_before) for v in views]
    return Page(items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


@router.post(
    "",
    response_model=RecurringPaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создание регулярного платежа",
    description="Если срок ближе, чем за REMIND_DAYS_BEFORE дней, напоминание уходит сразу.",
)
async def create_payment(
    body: RecurringPaymentCreate,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    reminders: RemindersDep,
    background: BackgroundTasks,
    scope: ActorScopeDep,
) -> RecurringPaymentOut:
    payment = await payments_service.create_payment(
        session,
        body,
        actor=admin,
        today=today,
        horizon_days=settings.occurrence_horizon_days,
        ip=client_ip(request),
    )
    # Платёж добавили позже, чем за N дней до срока, — напоминание сразу, не дожидаясь проверки worker'а.
    background.add_task(reminders.run, payment_id=payment.id)
    view, _ = await payments_service.get_payment(session, payment.id, today=today, scope=scope)
    return payment_out(view, today=today, remind_days_before=settings.remind_days_before)


@router.get(
    "/{payment_id}",
    response_model=RecurringPaymentDetailOut,
    summary="Получение регулярного платежа со всеми периодами",
    responses=_NOT_FOUND,
)
async def get_payment(
    payment_id: uuid.UUID, session: SessionDep, settings: SettingsDep, today: TodayDep, scope: TeamScopeDep
) -> RecurringPaymentDetailOut:
    view, occurrences = await payments_service.get_payment(session, payment_id, today=today, scope=scope)
    return payment_detail_out(view, occurrences, today=today, remind_days_before=settings.remind_days_before)


@router.delete(
    "/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Прекращение регулярного платежа и его напоминаний с сохранением истории",
    responses=_NOT_FOUND,
)
async def stop_payment(
    payment_id: uuid.UUID, admin: AdminUser, request: Request, session: SessionDep, today: TodayDep
) -> None:
    await payments_service.stop_payment(
        session, payment_id, actor=admin, today=today, now=utc_now(), ip=client_ip(request)
    )
