import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.enums import Currency, Period
from app.models import RecurringPayment, Team
from app.services.occurrences import missing_occurrences, team_start

TODAY = date(2026, 10, 15)
MSK = ZoneInfo("Europe/Moscow")


def _payment(first: date, period: Period = Period.MONTHLY, end: date | None = None) -> RecurringPayment:
    return RecurringPayment(
        id=uuid.uuid4(),
        name="Аренда",
        amount=Decimal("100.00"),
        currency=Currency.RUB,
        period=period,
        first_due_date=first,
        end_date=end,
    )


def _dues(payment: RecurringPayment, **kwargs: object) -> list[date]:
    params: dict[str, object] = {
        "team_id": uuid.uuid4(),
        "last_seq": None,
        "last_due": None,
        "today": TODAY,
        "horizon_days": 60,
    } | kwargs
    return [row["due_date"] for row in missing_occurrences(payment, **params)]  # type: ignore[arg-type]


def test_new_payment_gets_every_period_until_horizon() -> None:
    # горизонт: 15.10 + 60 дней = 14.12
    assert _dues(_payment(date(2026, 10, 20))) == [date(2026, 10, 20), date(2026, 11, 20)]


def test_far_future_payment_still_gets_its_first_period() -> None:
    assert _dues(_payment(date(2027, 6, 1))) == [date(2027, 6, 1)]


def test_yearly_payment_always_has_one_future_period() -> None:
    assert _dues(_payment(date(2026, 3, 1), Period.YEARLY)) == [date(2026, 3, 1), date(2027, 3, 1)]


def test_continues_after_last_existing_period() -> None:
    payment = _payment(date(2026, 10, 20))

    assert _dues(payment, last_seq=1, last_due=date(2026, 11, 20)) == []
    assert _dues(payment, last_seq=0, last_due=date(2026, 10, 20)) == [date(2026, 11, 20)]


def test_respects_end_date() -> None:
    assert _dues(_payment(date(2026, 1, 10), end=date(2026, 3, 10))) == [
        date(2026, 1, 10),
        date(2026, 2, 10),
        date(2026, 3, 10),
    ]


def test_team_joining_later_starts_from_its_first_due_on_or_after_joining() -> None:
    # команда подключилась 15.10: сроки 20.08 и 20.09 не её, первый — 20.10
    payment = _payment(date(2026, 8, 20))

    assert _dues(payment, start=date(2026, 10, 15)) == [date(2026, 10, 20), date(2026, 11, 20)]


def test_start_on_due_date_keeps_that_due() -> None:
    assert _dues(_payment(date(2026, 8, 20)), start=date(2026, 9, 20))[0] == date(2026, 9, 20)


def _team_start(team_created: datetime, payment_created: datetime, *, shared: bool = True) -> date | None:
    payment = _payment(date(2026, 8, 20))
    payment.team_id, payment.created_at = (None if shared else uuid.uuid4()), payment_created
    return team_start(payment, Team(name="Студия", created_at=team_created), MSK)


def test_shared_payment_counts_for_new_team_only_from_its_creation_day() -> None:
    # 23:30 UTC 14.10 — это уже 15.10 по Москве
    assert _team_start(datetime(2026, 10, 14, 23, 30, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)) == date(
        2026, 10, 15
    )


def test_team_created_before_or_same_day_as_payment_gets_all_dues() -> None:
    assert _team_start(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)) is None
    assert _team_start(datetime(2026, 8, 1, 15, tzinfo=UTC), datetime(2026, 8, 1, 9, tzinfo=UTC)) is None


def test_team_payment_always_starts_from_its_first_due() -> None:
    assert _team_start(datetime(2026, 10, 14, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC), shared=False) is None
