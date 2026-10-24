"""Инварианты, которые держит сама база данных, а не только код приложения."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    BudgetPeriodType,
    Currency,
    NotificationChannel,
    NotificationKind,
    OccurrenceStatus,
    Period,
    Role,
)
from app.models import Budget, Notification, PaymentOccurrence, RecurringPayment, Team, User

DUE = date(2026, 11, 1)


async def _team(session: AsyncSession, name: str = "Kefcoders") -> Team:
    team = await session.scalar(select(Team).where(Team.name == name))
    if team is None:
        team = Team(name=name)
        session.add(team)
        await session.flush()
    return team


async def _user(session: AsyncSession, login: str = "anna", *, is_system: bool = False) -> User:
    team_id = None if is_system else (await _team(session)).id
    user = User(
        login=login,
        password_hash="x",
        role=Role.ADMIN if is_system else Role.USER,
        is_system=is_system,
        team_id=team_id,
    )
    session.add(user)
    await session.flush()
    return user


async def _payment(session: AsyncSession) -> RecurringPayment:
    author = await _user(session, "admin", is_system=True)
    payment = RecurringPayment(
        name="Аренда офиса",
        amount=Decimal("50000.00"),
        currency=Currency.RUB,
        period=Period.MONTHLY,
        first_due_date=DUE,
        created_by=author.id,
        team_id=(await _team(session)).id,
    )
    session.add(payment)
    await session.flush()
    return payment


def _occurrence(payment: RecurringPayment, seq: int = 0, **fields: object) -> PaymentOccurrence:
    defaults: dict[str, object] = {"due_date": DUE, "amount": payment.amount, "currency": payment.currency}
    defaults["team_id"] = payment.team_id
    return PaymentOccurrence(recurring_payment_id=payment.id, seq=seq, **{**defaults, **fields})


async def _assert_rejected(session: AsyncSession, *objects: object) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add_all(objects)
            await session.flush()


async def test_new_occurrence_is_unpaid_by_default(db_session: AsyncSession) -> None:
    occurrence = _occurrence(await _payment(db_session))
    db_session.add(occurrence)
    await db_session.flush()
    await db_session.refresh(occurrence)

    assert occurrence.status is OccurrenceStatus.UNPAID
    assert occurrence.paid_date is None


async def test_paid_occurrence_requires_paid_date(db_session: AsyncSession) -> None:
    payment = await _payment(db_session)

    await _assert_rejected(db_session, _occurrence(payment, status=OccurrenceStatus.PAID))


async def test_unpaid_occurrence_cannot_keep_paid_date(db_session: AsyncSession) -> None:
    payment = await _payment(db_session)

    await _assert_rejected(db_session, _occurrence(payment, paid_date=DUE))


async def test_same_period_cannot_be_created_twice(db_session: AsyncSession) -> None:
    payment = await _payment(db_session)
    db_session.add(_occurrence(payment, seq=0))
    await db_session.flush()

    await _assert_rejected(db_session, _occurrence(payment, seq=0))


async def test_reminder_for_same_period_and_channel_is_stored_once(db_session: AsyncSession) -> None:
    occurrence = _occurrence(await _payment(db_session))
    db_session.add(occurrence)
    await db_session.flush()

    def reminder() -> Notification:
        return Notification(
            occurrence_id=occurrence.id, channel=NotificationChannel.TELEGRAM, kind=NotificationKind.BEFORE_DUE
        )

    db_session.add(reminder())
    await db_session.flush()

    await _assert_rejected(db_session, reminder())


async def test_login_is_unique_regardless_of_case(db_session: AsyncSession) -> None:
    await _user(db_session, "anna")

    team = await _team(db_session)
    await _assert_rejected(db_session, User(login="Anna", password_hash="x", role=Role.USER, team_id=team.id))


async def test_only_one_system_admin_exists(db_session: AsyncSession) -> None:
    await _user(db_session, "admin", is_system=True)

    await _assert_rejected(db_session, User(login="root", password_hash="x", role=Role.ADMIN, is_system=True))


async def test_yearly_budget_is_unique_per_team_currency_and_year(db_session: AsyncSession) -> None:
    kefcoders, studio = await _team(db_session), await _team(db_session, "Студия дизайна")

    def yearly(team: Team) -> Budget:
        return Budget(
            team_id=team.id, currency=Currency.USD, period_type=BudgetPeriodType.YEAR, year=2026, amount=Decimal(600)
        )

    db_session.add_all([yearly(kefcoders), yearly(studio)])  # у каждой команды свой бюджет
    await db_session.flush()

    await _assert_rejected(db_session, yearly(kefcoders))


# ---------- команды ----------


async def test_admin_is_not_in_a_team(db_session: AsyncSession) -> None:
    team = await _team(db_session)

    await _assert_rejected(db_session, User(login="root", password_hash="x", role=Role.ADMIN, team_id=team.id))


async def test_team_name_is_unique_regardless_of_case(db_session: AsyncSession) -> None:
    await _team(db_session, "Kefcoders")

    await _assert_rejected(db_session, Team(name="KEFCODERS"))


async def test_shared_payment_period_exists_once_per_team(db_session: AsyncSession) -> None:
    payment = await _payment(db_session)
    payment.team_id = None  # общий платёж
    studio = await _team(db_session, "Студия дизайна")
    db_session.add_all(
        [_occurrence(payment, team_id=(await _team(db_session)).id), _occurrence(payment, team_id=studio.id)]
    )
    await db_session.flush()

    await _assert_rejected(db_session, _occurrence(payment, team_id=studio.id))


async def test_team_with_members_cannot_be_deleted(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    team = await db_session.get(Team, user.team_id)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.delete(team)
            await db_session.flush()


async def test_amount_must_be_positive(db_session: AsyncSession) -> None:
    payment = await _payment(db_session)

    await _assert_rejected(db_session, _occurrence(payment, amount=Decimal(0)))


async def test_enums_are_stored_as_lowercase_values(db_session: AsyncSession) -> None:
    payment = await _payment(db_session)

    stored = await db_session.scalar(
        text("SELECT period::text FROM recurring_payments WHERE id = :id"), {"id": payment.id}
    )

    assert stored == "monthly"
