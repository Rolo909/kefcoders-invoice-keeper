from datetime import date

import pytest

from app.domain.enums import Period
from app.domain.schedule import due_date, first_seq_on_or_after, occurrences_between


def _dues(first: date, period: Period, count: int) -> list[date]:
    return [due_date(first, period, n) for n in range(count)]


def test_monthly_31st_falls_back_to_last_day_and_returns_to_31st() -> None:
    assert _dues(date(2025, 1, 31), Period.MONTHLY, 4) == [
        date(2025, 1, 31),
        date(2025, 2, 28),
        date(2025, 3, 31),
        date(2025, 4, 30),
    ]


def test_monthly_31st_uses_29th_february_in_leap_year() -> None:
    assert due_date(date(2024, 1, 31), Period.MONTHLY, 1) == date(2024, 2, 29)


def test_monthly_30th_keeps_anchor_day_after_february() -> None:
    assert _dues(date(2025, 1, 30), Period.MONTHLY, 3) == [date(2025, 1, 30), date(2025, 2, 28), date(2025, 3, 30)]


def test_monthly_crosses_year_boundary() -> None:
    assert due_date(date(2025, 11, 15), Period.MONTHLY, 3) == date(2026, 2, 15)


def test_yearly_29th_february_clamps_and_restores_in_leap_year() -> None:
    first = date(2024, 2, 29)

    assert due_date(first, Period.YEARLY, 1) == date(2025, 2, 28)
    assert due_date(first, Period.YEARLY, 4) == date(2028, 2, 29)


def test_quarterly_adds_three_months_from_anchor() -> None:
    assert _dues(date(2025, 11, 30), Period.QUARTERLY, 3) == [date(2025, 11, 30), date(2026, 2, 28), date(2026, 5, 30)]


def test_weekly_adds_seven_days() -> None:
    assert _dues(date(2025, 12, 29), Period.WEEKLY, 2) == [date(2025, 12, 29), date(2026, 1, 5)]


def test_negative_seq_is_rejected() -> None:
    with pytest.raises(ValueError, match="отрицательным"):
        due_date(date(2025, 1, 1), Period.MONTHLY, -1)


@pytest.mark.parametrize("period", list(Period))
@pytest.mark.parametrize("day", [date(2024, 1, 1), date(2025, 3, 1), date(2025, 3, 31), date(2030, 7, 15)])
def test_first_seq_on_or_after_matches_brute_force(period: Period, day: date) -> None:
    first = date(2025, 1, 31)
    expected = next(n for n in range(2000) if due_date(first, period, n) >= day)

    assert first_seq_on_or_after(first, period, day) == expected


def test_occurrences_between_includes_range_bounds() -> None:
    result = list(occurrences_between(date(2025, 1, 31), Period.MONTHLY, date(2025, 2, 28), date(2025, 4, 30)))

    assert result == [(1, date(2025, 2, 28)), (2, date(2025, 3, 31)), (3, date(2025, 4, 30))]


def test_occurrences_between_stops_at_payment_end_date() -> None:
    result = list(
        occurrences_between(
            date(2025, 1, 10), Period.MONTHLY, date(2025, 1, 1), date(2025, 12, 31), until=date(2025, 3, 10)
        )
    )

    assert [d for _, d in result] == [date(2025, 1, 10), date(2025, 2, 10), date(2025, 3, 10)]


def test_occurrences_between_is_empty_before_first_due() -> None:
    assert list(occurrences_between(date(2026, 1, 1), Period.MONTHLY, date(2025, 1, 1), date(2025, 12, 31))) == []
