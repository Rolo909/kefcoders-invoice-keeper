"""Тестовые данные дают все состояния, нужные сценарию защиты, и создаются ровно один раз."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Currency, OccurrenceState
from app.domain.status import occurrence_state
from app.models import Budget, PaymentOccurrence, RecurringPayment, Team, User
from app.security import verify_password
from app.seed import DEMO_USERS, KEF, STUDIO, seed_demo_data

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
    rent = await periods_of(db_session, "Аренда офиса")

    upcoming = [p for p in rent if p.paid_date is None]
    assert upcoming[0].due_date == TODAY + timedelta(days=2)
    assert states(upcoming)[0] is OccurrenceState.DUE_SOON
    assert set(states(rent[:4])) == {OccurrenceState.PAID}
    assert {p.currency for p in rent} == {Currency.RUB}


@pytest.mark.usefixtures("seeded")
async def test_server_in_dollars_is_overdue(db_session: AsyncSession) -> None:
    server = await periods_of(db_session, "Сервер DigitalOcean")

    overdue = [p for p, s in zip(server, states(server), strict=True) if s is OccurrenceState.OVERDUE]
    assert [p.due_date for p in overdue] == [TODAY - timedelta(days=10)]
    assert {p.currency for p in server} == {Currency.USD}


@pytest.mark.usefixtures("seeded")
async def test_subscription_in_euro_shows_last_day_rule_and_late_payment(db_session: AsyncSession) -> None:
    figma = await periods_of(db_session, "Figma Professional")

    assert figma[0].due_date == date(2026, 7, 31)
    assert [p.due_date for p in figma[1:4]] == [date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 31)]
    assert states(figma)[:3] == [OccurrenceState.PAID, OccurrenceState.PAID, OccurrenceState.PAID_LATE]
    assert {p.currency for p in figma} == {Currency.EUR}


@pytest.mark.usefixtures("seeded")
async def test_stopped_payment_keeps_its_history(db_session: AsyncSession) -> None:
    hosting = await db_session.scalar(select(RecurringPayment).where(RecurringPayment.name == "Хостинг Timeweb"))

    assert hosting is not None
    assert hosting.deleted_at is not None
    assert all(p.paid_date is not None for p in await periods_of(db_session, "Хостинг Timeweb"))


@pytest.mark.usefixtures("seeded")
async def test_budgets_cover_every_currency_for_month_and_year(db_session: AsyncSession) -> None:
    budgets = list(await db_session.scalars(select(Budget)))

    assert {(b.currency, b.period_type.value, b.month) for b in budgets} == {
        (currency, kind, month) for currency in Currency for kind, month in (("month", 10), ("year", None))
    }


async def test_nothing_is_created_without_admin(db_session: AsyncSession) -> None:
    assert not await seed_demo_data(db_session, today=TODAY, tz=TZ)
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


# ---------- команды ----------


async def team_named(session: AsyncSession, name: str) -> Team:
    team = await session.scalar(select(Team).where(Team.name == name))
    assert team is not None
    return team


@pytest.mark.usefixtures("seeded")
async def test_two_teams_with_their_members(db_session: AsyncSession) -> None:
    rows = await db_session.execute(select(User.login, Team.name).join(Team, Team.id == User.team_id))

    assert sorted((login, team) for login, team in rows.all()) == [
        ("anna", KEF),
        ("maria", KEF),
        ("oleg", STUDIO),
        ("user", KEF),
    ]


@pytest.mark.usefixtures("seeded")
async def test_shared_payment_is_paid_by_each_team_separately(db_session: AsyncSession) -> None:
    studio = await team_named(db_session, STUDIO)
    accounting = await periods_of(db_session, "Бухгалтерское сопровождение")
    by_team: dict[str, list[PaymentOccurrence]] = {KEF: [], STUDIO: []}
    for period in accounting:
        by_team[STUDIO if period.team_id == studio.id else KEF].append(period)

    # У Студии нет сроков раньше дня её создания — долгов за прошлое нет.
    assert min(p.due_date for p in by_team[STUDIO]) >= TODAY - timedelta(days=100)
    assert len(by_team[KEF]) > len(by_team[STUDIO])
    # Прошлый месяц Kefcoders оплатил, Студия — нет.
    last_month = TODAY - timedelta(days=30)
    kef_last = next(p for p in by_team[KEF] if abs((p.due_date - last_month).days) < 5)
    studio_last = next(p for p in by_team[STUDIO] if abs((p.due_date - last_month).days) < 5)
    assert states([kef_last, studio_last]) == [OccurrenceState.PAID, OccurrenceState.OVERDUE]


@pytest.mark.usefixtures("seeded")
async def test_studio_has_its_own_payments(db_session: AsyncSession) -> None:
    studio = await team_named(db_session, STUDIO)
    rent = await periods_of(db_session, "Аренда студии")
    adobe = await periods_of(db_session, "Adobe Creative Cloud")
    stock = await periods_of(db_session, "Shutterstock")

    assert {p.team_id for p in [*rent, *adobe, *stock]} == {studio.id}
    assert next(p.due_date for p in rent if p.paid_date is None) == TODAY + timedelta(days=6)
    assert [p.due_date for p, s in zip(adobe, states(adobe), strict=True) if s is OccurrenceState.OVERDUE] == [
        TODAY - timedelta(days=2)
    ]
    assert OccurrenceState.PAID in states(stock)


@pytest.mark.usefixtures("seeded")
async def test_each_team_has_its_own_budgets(db_session: AsyncSession) -> None:
    rows = await db_session.execute(
        select(Team.name, func.count()).join(Budget, Budget.team_id == Team.id).group_by(Team.name)
    )

    assert {name: count for name, count in rows.all()} == {KEF: 6, STUDIO: 6}
