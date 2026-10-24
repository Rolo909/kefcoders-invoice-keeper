from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import OccurrenceState, OccurrenceStatus
from app.domain.status import days_overdue, is_overdue, occurrence_state, today_in

DUE = date(2026, 10, 25)
REMIND_DAYS = 3


@dataclass
class Occ:
    status: OccurrenceStatus
    due_date: date
    paid_date: date | None = None


def unpaid() -> Occ:
    return Occ(OccurrenceStatus.UNPAID, DUE)


def paid_on(day: date) -> Occ:
    return Occ(OccurrenceStatus.PAID, DUE, day)


def test_unpaid_is_not_overdue_on_due_date() -> None:
    assert not is_overdue(unpaid(), today=DUE)


def test_unpaid_is_overdue_from_next_day() -> None:
    assert is_overdue(unpaid(), today=date(2026, 10, 26))


def test_payment_on_due_date_is_on_time() -> None:
    assert not is_overdue(paid_on(DUE), today=date(2026, 11, 30))


def test_payment_after_due_date_is_overdue() -> None:
    assert is_overdue(paid_on(date(2026, 10, 27)), today=date(2026, 10, 27))


def test_correcting_paid_date_removes_overdue_without_touching_due_date() -> None:
    occurrence = paid_on(date(2026, 10, 27))

    occurrence.paid_date = date(2026, 10, 24)

    assert not is_overdue(occurrence, today=date(2026, 11, 1))
    assert occurrence.due_date == DUE


def test_cancelled_payment_is_judged_by_today() -> None:
    occurrence = Occ(OccurrenceStatus.UNPAID, DUE, paid_date=None)

    assert is_overdue(occurrence, today=date(2026, 11, 1))
    assert days_overdue(occurrence, today=date(2026, 11, 1)) == 7


def test_days_overdue_counts_until_payment() -> None:
    assert days_overdue(paid_on(date(2026, 10, 28)), today=date(2026, 12, 1)) == 3


def test_days_overdue_is_zero_before_due_date() -> None:
    assert days_overdue(unpaid(), today=date(2026, 10, 20)) == 0


@pytest.mark.parametrize(
    ("occurrence", "today", "expected"),
    [
        (paid_on(DUE), date(2026, 10, 30), OccurrenceState.PAID),
        (paid_on(date(2026, 10, 26)), date(2026, 10, 30), OccurrenceState.PAID_LATE),
        (unpaid(), date(2026, 10, 26), OccurrenceState.OVERDUE),
        (unpaid(), DUE, OccurrenceState.DUE_SOON),
        (unpaid(), date(2026, 10, 22), OccurrenceState.DUE_SOON),
        (unpaid(), date(2026, 10, 21), OccurrenceState.UPCOMING),
    ],
)
def test_occurrence_state(occurrence: Occ, today: date, expected: OccurrenceState) -> None:
    assert occurrence_state(occurrence, today, REMIND_DAYS) == expected


def test_today_uses_application_timezone_not_utc() -> None:
    late_evening_utc = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)

    assert today_in(ZoneInfo("Europe/Moscow"), now=late_evening_utc) == date(2026, 10, 25)
    assert today_in(ZoneInfo("UTC"), now=late_evening_utc) == date(2026, 10, 24)
