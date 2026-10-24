import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, SettingsDep, TodayDep
from app.db import SessionDep
from app.domain.enums import Currency, NotificationKind, OccurrenceState
from app.domain.status import occurrence_state
from app.services import inbox as inbox_service

router = APIRouter(prefix="/inbox", tags=["inbox"])


class InboxItemOut(BaseModel):
    id: uuid.UUID
    occurrence_id: uuid.UUID
    kind: NotificationKind
    created_at: datetime
    read: bool
    payment_name: str
    amount: Decimal
    currency: Currency
    due_date: date
    occurrence_state: OccurrenceState
    paid_date: date | None
    payment_deleted: bool


class InboxOut(BaseModel):
    items: list[InboxItemOut]
    unread_count: int


@router.get("", response_model=InboxOut, summary="Уведомления в колокольчике панели (последние 30)")
async def inbox(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    unread_only: Annotated[bool, Query(description="Только непрочитанные")] = False,
) -> InboxOut:
    entries, unread = await inbox_service.list_inbox(session, user, unread_only=unread_only)
    items = [
        InboxItemOut(
            id=e.notification.id,
            occurrence_id=e.occurrence.id,
            kind=e.notification.kind,
            created_at=e.notification.created_at,
            read=e.read,
            payment_name=e.payment.name,
            amount=e.occurrence.amount,
            currency=e.occurrence.currency,
            due_date=e.occurrence.due_date,
            occurrence_state=occurrence_state(e.occurrence, today, settings.remind_days_before),
            paid_date=e.occurrence.paid_date,
            payment_deleted=e.payment.deleted_at is not None,
        )
        for e in entries
    ]
    return InboxOut(items=items, unread_count=unread)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="Отметить все уведомления прочитанными")
async def read_all(user: CurrentUser, session: SessionDep) -> None:
    await inbox_service.mark_all_read(session, user)


@router.post(
    "/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="Отметить уведомление прочитанным"
)
async def read_one(notification_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    await inbox_service.mark_read(session, user, notification_id)
