import uuid
from datetime import date
from decimal import Decimal

from app.domain.enums import Currency, Period
from app.models import RecurringPayment
from app.services.occurrences import missing_occurrences

TODAY = date(2026, 10, 15)


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
    params: dict[str, object] = {"last_seq": None, "last_due": None, "today": TODAY, "horizon_days": 60} | kwargs
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
