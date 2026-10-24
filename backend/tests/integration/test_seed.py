"""Тестовые данные дают все состояния, нужные сценарию защиты, и создаются ровно один раз."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Currency, OccurrenceState
from app.domain.status import occurrence_state
from app.models import Budget, PaymentOccurrence, RecurringPayment, User
from app.security import verify_password
from app.seed import DEMO_USERS, seed_demo_data

TODAY = date(2026, 10, 24)
TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
async def seeded(db_session: AsyncSession, admin: User) -> None:
    assert await seed_demo_data(db_session, today=TODAY, tz=TZ)


async def periods_of(session: AsyncSession, name: str) -> list[PaymentOccurrence]:
    stmt = (
        select(PaymentOccurrence)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .where(RecurringPayment.name == name)
        .order_by(PaymentOccurrence.seq)
    )
    return list(await session.scalars(stmt))


def states(periods: list[PaymentOccurrence]) -> list[OccurrenceState]:
    return [occurrence_state(p, TODAY, 3) for p in periods]


@pytest.mark.usefixtures("seeded")
async def test_second_run_changes_nothing(db_session: AsyncSession) -> None:
    payments_before = await db_session.scalar(select(func.count()).select_from(RecurringPayment))

    assert not await seed_demo_data(db_session, today=TODAY, tz=TZ)
    assert await db_session.scalar(select(func.count()).select_from(RecurringPayment)) == payments_before


@pytest.mark.usefixtures("seeded")
async def test_demo_users_can_log_in(db_session: AsyncSession) -> None:
    for login, password, *_ in DEMO_USERS:
        user = await db_session.scalar(select(User).where(User.login == login))
        assert user is not None
        assert verify_password(password, user.password_hash)


@pytest.mark.usefixtures("seeded")
async def test_rent_in_rubles_is_due_in_two_days(db_session: AsyncSession) -> None:
    rent = await periods_of(db_session, "Аренда офиса, Санкт-Петербург")

    upcoming = [p for p in rent if p.paid_date is None]
    assert upcoming[0].due_date == TODAY + timedelta(days=2)
    assert states(upcoming)[0] is OccurrenceState.DUE_SOON
    assert set(states(rent[:4])) == {OccurrenceState.PAID}
    assert {p.currency for p in rent} == {Currency.RUB}


@pytest.mark.usefixtures("seeded")
async def test_server_in_dollars_is_overdue(db_session: AsyncSession) -> None:
    server = await periods_of(db_session, "IP-транзит, канал 10 Гбит/с")

    overdue = [p for p, s in zip(server, states(server), strict=True) if s is OccurrenceState.OVERDUE]
    assert [p.due_date for p in overdue] == [TODAY - timedelta(days=10)]
    assert {p.currency for p in server} == {Currency.USD}


@pytest.mark.usefixtures("seeded")
async def test_subscription_in_euro_shows_last_day_rule_and_late_payment(db_session: AsyncSession) -> None:
    figma = await periods_of(db_session, "Аренда стойки, Амстердам")

    assert figma[0].due_date == date(2026, 7, 31)
    assert [p.due_date for p in figma[1:4]] == [date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 31)]
    assert states(figma)[:3] == [OccurrenceState.PAID, OccurrenceState.PAID, OccurrenceState.PAID_LATE]
    assert {p.currency for p in figma} == {Currency.EUR}


@pytest.mark.usefixtures("seeded")
async def test_stopped_payment_keeps_its_history(db_session: AsyncSession) -> None:
    hosting = await db_session.scalar(select(RecurringPayment).where(RecurringPayment.name == "Резервный канал связи"))

    assert hosting is not None
    assert hosting.deleted_at is not None
    assert all(p.paid_date is not None for p in await periods_of(db_session, "Резервный канал связи"))


@pytest.mark.usefixtures("seeded")
async def test_budgets_cover_every_currency_for_month_and_year(db_session: AsyncSession) -> None:
    budgets = list(await db_session.scalars(select(Budget)))

    assert {(b.currency, b.period_type.value, b.month) for b in budgets} == {
        (currency, kind, month) for currency in Currency for kind, month in (("month", 10), ("year", None))
    }


async def test_nothing_is_created_without_admin(db_session: AsyncSession) -> None:
    assert not await seed_demo_data(db_session, today=TODAY, tz=TZ)
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0
