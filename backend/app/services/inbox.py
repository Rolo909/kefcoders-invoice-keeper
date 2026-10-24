"""Лента уведомлений в колокольчике панели: общая для команды, «прочитано» — у каждого своё."""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Exists, exists, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import NotificationChannel, NotificationStatus
from app.errors import not_found
from app.models import Notification, NotificationRead, PaymentOccurrence, RecurringPayment, Team, User
from app.services.scope import TeamScope

INBOX_SIZE = 30

_inapp_sent = (Notification.channel == NotificationChannel.INAPP, Notification.status == NotificationStatus.SENT)


def _is_read(user: User) -> Exists:
    return exists().where(NotificationRead.notification_id == Notification.id, NotificationRead.user_id == user.id)


@dataclass(frozen=True)
class InboxEntry:
    notification: Notification
    occurrence: PaymentOccurrence
    payment: RecurringPayment
    team: Team
    read: bool


def _visible(scope: TeamScope) -> list[ColumnElement[bool]]:
    """Уведомления о периодах видимых команд."""
    return [
        *_inapp_sent,
        Notification.occurrence_id.in_(select(PaymentOccurrence.id).where(*scope.where(PaymentOccurrence.team_id))),
    ]


async def list_inbox(
    session: AsyncSession, user: User, *, unread_only: bool, scope: TeamScope
) -> tuple[list[InboxEntry], int]:
    """Последние уведомления своей команды (новые сверху) и число непрочитанных среди них."""
    is_read = _is_read(user)
    stmt = (
        select(Notification, PaymentOccurrence, RecurringPayment, Team, is_read)
        .join(PaymentOccurrence, PaymentOccurrence.id == Notification.occurrence_id)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .join(Team, Team.id == PaymentOccurrence.team_id)
        .where(*_visible(scope))
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(INBOX_SIZE)
    )
    if unread_only:
        stmt = stmt.where(~is_read)
    entries = [InboxEntry(n, o, p, t, bool(read)) for n, o, p, t, read in await session.execute(stmt)]
    unread = await session.scalar(select(func.count()).select_from(Notification).where(*_visible(scope), ~is_read))
    return entries, unread or 0


async def mark_read(session: AsyncSession, user: User, notification_id: uuid.UUID, *, scope: TeamScope) -> None:
    found = await session.scalar(select(Notification.id).where(Notification.id == notification_id, *_visible(scope)))
    if found is None:
        raise not_found("Уведомление не найдено")
    await session.execute(
        pg_insert(NotificationRead)
        .values(user_id=user.id, notification_id=notification_id)
        .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
    )
    await session.commit()


async def mark_all_read(session: AsyncSession, user: User, *, scope: TeamScope) -> None:
    await session.execute(
        pg_insert(NotificationRead)
        .from_select(
            ["user_id", "notification_id"],
            select(literal(user.id), Notification.id).where(*_visible(scope)),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
    )
    await session.commit()
