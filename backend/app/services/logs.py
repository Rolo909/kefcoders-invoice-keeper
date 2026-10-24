"""Журнал действий и журнал отправленных напоминаний (для администратора)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import NotificationChannel, NotificationStatus
from app.models import AuditLog, Notification, PaymentOccurrence, RecurringPayment, Team, User


@dataclass(frozen=True)
class AuditFilter:
    action: str | None = None
    actor_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


def _day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _audit_conditions(filters: AuditFilter, tz: ZoneInfo) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.action:
        # «auth» находит все auth.*, «auth.login» — только вход.
        conditions.append(or_(AuditLog.action == filters.action, AuditLog.action.startswith(f"{filters.action}.")))
    if filters.actor_id is not None:
        conditions.append(AuditLog.actor_id == filters.actor_id)
    if filters.date_from is not None:  # границы дней — в часовом поясе приложения
        conditions.append(AuditLog.at >= _day_start(filters.date_from, tz))
    if filters.date_to is not None:
        conditions.append(AuditLog.at < _day_start(filters.date_to + timedelta(days=1), tz))
    return conditions


async def list_audit_logs(
    session: AsyncSession, filters: AuditFilter, *, tz: ZoneInfo, limit: int, offset: int
) -> tuple[list[tuple[AuditLog, User | None]], int]:
    """Записи журнала, новые сверху."""
    conditions = _audit_conditions(filters, tz)
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    rows = await session.execute(
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(*conditions)
        .order_by(AuditLog.at.desc(), AuditLog.id)
        .limit(limit)
        .offset(offset)
    )
    return [(log, actor) for log, actor in rows], total


async def list_notifications(
    session: AsyncSession,
    *,
    channel: NotificationChannel | None,
    status: NotificationStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Notification, PaymentOccurrence, RecurringPayment, Team]], int]:
    """Напоминания по всем каналам, новые сверху."""
    conditions: list[ColumnElement[bool]] = []
    if channel is not None:
        conditions.append(Notification.channel == channel)
    if status is not None:
        conditions.append(Notification.status == status)
    total = await session.scalar(select(func.count()).select_from(Notification).where(*conditions)) or 0
    rows = await session.execute(
        select(Notification, PaymentOccurrence, RecurringPayment, Team)
        .join(PaymentOccurrence, PaymentOccurrence.id == Notification.occurrence_id)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .join(Team, Team.id == PaymentOccurrence.team_id)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(limit)
        .offset(offset)
    )
    return [(n, o, p, t) for n, o, p, t in rows], total
