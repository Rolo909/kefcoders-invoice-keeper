import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, status

from app.api.deps import CurrentUser, SettingsDep, TodayDep, client_ip, utc_now
from app.api.v1.presenters import occurrence_detail_out, occurrence_out
from app.db import SessionDep
from app.domain.enums import Currency, OccurrenceState, OccurrenceStatus
from app.schemas.common import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery, Page
from app.schemas.payment import OccurrenceDetailOut, OccurrenceOut, OccurrenceUpdate
from app.services import occurrences as occurrences_service
from app.services.occurrences import OccurrenceFilter

router = APIRouter(prefix="/payment-occurrences", tags=["payment-occurrences"])

OccurrenceSort = Literal["due_date", "-due_date", "amount", "-amount", "days_overdue", "-days_overdue"]

_NOT_FOUND: dict[int | str, dict[str, str]] = {status.HTTP_404_NOT_FOUND: {"description": "Период не найден"}}


@router.get(
    "",
    response_model=Page[OccurrenceOut],
    summary="Получение списка платежей (периодов), в том числе оплаченных и просроченных",
)
async def list_occurrences(
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    status_: Annotated[OccurrenceStatus | None, Query(alias="status")] = None,
    overdue: Annotated[bool | None, Query(description="true — только просроченные, false — без просрочки")] = None,
    state: OccurrenceState | None = None,
    date_from: Annotated[date | None, Query(description="Срок не раньше")] = None,
    date_to: Annotated[date | None, Query(description="Срок не позже")] = None,
    currency: Annotated[list[Currency] | None, Query(description="Можно повторять: currency=RUB&currency=USD")] = None,
    recurring_payment_id: uuid.UUID | None = None,
    sort: OccurrenceSort = "due_date",
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
) -> Page[OccurrenceOut]:
    await occurrences_service.ensure_occurrences(session, today=today, horizon_days=settings.occurrence_horizon_days)
    await session.commit()
    filters = OccurrenceFilter(
        status=status_,
        overdue=overdue,
        state=state,
        date_from=date_from,
        date_to=date_to,
        currencies=currency or [],
        recurring_payment_id=recurring_payment_id,
    )
    views, total = await occurrences_service.list_occurrences(
        session,
        filters,
        sort=sort,
        limit=limit,
        offset=offset,
        today=today,
        remind_days_before=settings.remind_days_before,
    )
    items = [occurrence_out(v, today=today, remind_days_before=settings.remind_days_before) for v in views]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{occurrence_id}",
    response_model=OccurrenceDetailOut,
    summary="Получение конкретного платежа (периода) с историей изменений и напоминаниями",
    responses=_NOT_FOUND,
)
async def get_occurrence(
    occurrence_id: uuid.UUID, session: SessionDep, settings: SettingsDep, today: TodayDep
) -> OccurrenceDetailOut:
    detail = await occurrences_service.get_occurrence_detail(session, occurrence_id)
    return occurrence_detail_out(detail, today=today, remind_days_before=settings.remind_days_before)


@router.patch(
    "/{occurrence_id}",
    response_model=OccurrenceOut,
    summary="Подтверждение или отмена оплаты, исправление фактической даты оплаты",
    responses={
        **_NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "description": "already_paid — период уже оплачен (кем и когда — в detail); "
            "not_paid — дату можно менять только у оплаченного периода"
        },
    },
)
async def update_occurrence(
    occurrence_id: uuid.UUID,
    body: OccurrenceUpdate,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
) -> OccurrenceOut:
    view = await occurrences_service.update_occurrence(
        session,
        occurrence_id,
        new_status=body.status,
        paid_date=body.paid_date,
        actor=user,
        today=today,
        now=utc_now(),
        ip=client_ip(request),
    )
    return occurrence_out(view, today=today, remind_days_before=settings.remind_days_before)
