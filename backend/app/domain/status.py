"""Статус периода и просрочка.

Просрочка не хранится, а вычисляется: исправление фактической даты оплаты сразу её пересчитывает,
срок при этом не меняется.
"""

from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.enums import OccurrenceState, OccurrenceStatus


class OccurrenceLike(Protocol):
    @property
    def status(self) -> OccurrenceStatus: ...

    @property
    def due_date(self) -> date: ...

    @property
    def paid_date(self) -> date | None: ...


def today_in(timezone: ZoneInfo, now: datetime | None = None) -> date:
    """«Сегодня» в едином часовом поясе приложения, а не в системном времени контейнера."""
    moment = now if now is not None else datetime.now(timezone)
    return moment.astimezone(timezone).date()


def _paid_date(occurrence: OccurrenceLike) -> date | None:
    return occurrence.paid_date if occurrence.status is OccurrenceStatus.PAID else None


def is_overdue(occurrence: OccurrenceLike, today: date) -> bool:
    """Просрочка — со следующего дня после срока; оплата в день срока — вовремя."""
    paid_date = _paid_date(occurrence)
    if paid_date is not None:
        return paid_date > occurrence.due_date
    return today > occurrence.due_date


def days_overdue(occurrence: OccurrenceLike, today: date) -> int:
    """Дней просрочки: до фактической оплаты, а если не оплачено — до сегодня."""
    reference = _paid_date(occurrence) or today
    return max(0, (reference - occurrence.due_date).days)


def occurrence_state(occurrence: OccurrenceLike, today: date, remind_days_before: int) -> OccurrenceState:
    paid_date = _paid_date(occurrence)
    if paid_date is not None:
        return OccurrenceState.PAID_LATE if paid_date > occurrence.due_date else OccurrenceState.PAID
    days_left = (occurrence.due_date - today).days
    if days_left < 0:
        return OccurrenceState.OVERDUE
    if days_left <= remind_days_before:
        return OccurrenceState.DUE_SOON
    return OccurrenceState.UPCOMING
