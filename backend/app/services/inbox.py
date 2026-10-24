"""Лента уведомлений в колокольчике панели: общая для всех, «прочитано» — у каждого своё."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Exists, exists, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import NotificationChannel, NotificationStatus
from app.errors import not_found
from app.models import Notification, NotificationRead, PaymentOccurrence, RecurringPayment, User

INBOX_SIZE = 30

_inapp_sent = (Notification.channel == NotificationChannel.INAPP, Notification.status == NotificationStatus.SENT)


def _is_read(user: User) -> Exists:
    return exists().where(NotificationRead.notification_id == Notification.id, NotificationRead.user_id == user.id)


@dataclass(frozen=True)
class InboxEntry:
    notification: Notification
    occurrence: PaymentOccurrence
    payment: RecurringPayment
    read: bool


async def list_inbox(session: AsyncSession, user: User, *, unread_only: bool) -> tuple[list[InboxEntry], int]:
    """Последние уведомления (новые сверху) и число непрочитанных среди всех."""
    is_read = _is_read(user)
    stmt = (
        select(Notification, PaymentOccurrence, RecurringPayment, is_read)
        .join(PaymentOccurrence, PaymentOccurrence.id == Notification.occurrence_id)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .where(*_inapp_sent)
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(INBOX_SIZE)
    )
    if unread_only:
        stmt = stmt.where(~is_read)
    entries = [InboxEntry(n, o, p, bool(read)) for n, o, p, read in await session.execute(stmt)]
    unread = await session.scalar(select(func.count()).select_from(Notification).where(*_inapp_sent, ~is_read))
    return entries, unread or 0


async def mark_read(session: AsyncSession, user: User, notification_id: uuid.UUID) -> None:
    found = await session.scalar(select(Notification.id).where(Notification.id == notification_id, *_inapp_sent))
    if found is None:
        raise not_found("Уведомление не найдено")
    await session.execute(
        pg_insert(NotificationRead)
        .values(user_id=user.id, notification_id=notification_id)
        .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
    )
    await session.commit()


async def mark_all_read(session: AsyncSession, user: User) -> None:
    await session.execute(
        pg_insert(NotificationRead)
        .from_select(
            ["user_id", "notification_id"],
            select(literal(user.id), Notification.id).where(*_inapp_sent),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
    )
    await session.commit()
