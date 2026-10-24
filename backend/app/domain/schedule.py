"""Расчёт сроков периодов регулярного платежа.

Срок периода n всегда считается от якорной даты (первого срока), а не от предыдущего срока:
иначе платёж «31-го» после февраля навсегда съехал бы на 28-е.
"""

import calendar
from collections.abc import Iterator
from datetime import date, timedelta

from app.domain.enums import Period

_MONTHS_IN_PERIOD = {Period.MONTHLY: 1, Period.QUARTERLY: 3, Period.YEARLY: 12}
_DAYS_IN_WEEK = 7
_AVG_DAYS_IN_MONTH = 30


def add_months_clamped(anchor: date, months: int) -> date:
    """Сдвиг на месяцы с сохранением дня якоря; если такого числа нет — последний день месяца."""
    years, month_index = divmod(anchor.month - 1 + months, 12)
    year, month = anchor.year + years, month_index + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def due_date(first_due: date, period: Period, seq: int) -> date:
    """Срок периода с номером seq (0 — первый срок)."""
    if seq < 0:
        raise ValueError("Номер периода не может быть отрицательным")
    if period is Period.WEEKLY:
        return first_due + timedelta(weeks=seq)
    return add_months_clamped(first_due, _MONTHS_IN_PERIOD[period] * seq)


def _approx_seq(first_due: date, period: Period, day: date) -> int:
    days = (day - first_due).days
    if period is Period.WEEKLY:
        return max(0, days // _DAYS_IN_WEEK)
    return max(0, days // (_AVG_DAYS_IN_MONTH * _MONTHS_IN_PERIOD[period]))


def first_seq_on_or_after(first_due: date, period: Period, day: date) -> int:
    """Наименьший номер периода, срок которого не раньше day."""
    seq = _approx_seq(first_due, period, day)
    while seq > 0 and due_date(first_due, period, seq - 1) >= day:
        seq -= 1
    while due_date(first_due, period, seq) < day:
        seq += 1
    return seq


def occurrences_between(
    first_due: date,
    period: Period,
    start: date,
    end: date,
    *,
    until: date | None = None,
) -> Iterator[tuple[int, date]]:
    """Пары (номер, срок) для сроков в [start, end]; until — дата окончания платежа (включительно)."""
    last = end if until is None else min(end, until)
    seq = first_seq_on_or_after(first_due, period, start)
    current = due_date(first_due, period, seq)
    while current <= last:
        yield seq, current
        seq += 1
        current = due_date(first_due, period, seq)
