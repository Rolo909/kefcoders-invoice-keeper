"""Одновременная отметка оплаты одного периода двумя людьми — из двух отдельных подключений к БД.

Первый держит блокировку строки периода (SELECT … FOR UPDATE), второй в это время ждёт. После того
как первый отметил оплату, второй должен получить «уже оплачено», а не перезаписать дату и автора.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.enums import Currency, OccurrenceStatus, Period, Role
from app.errors import AppError
from app.models import AuditLog, PaymentOccurrence, RecurringPayment, Team, User
from app.services.occurrences import update_occurrence
from app.services.telegram import PayResult, mark_paid_from_telegram
from tests.conftest import TEST_DATABASE_URL

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
TG_ANNA, TG_MARIA = 777_001, 777_002


@dataclass(frozen=True)
class World:
    sessions: async_sessionmaker[AsyncSession]
    anna_id: uuid.UUID
    maria_id: uuid.UUID
    payment_id: uuid.UUID
    occurrence_id: uuid.UUID


@pytest.fixture
async def world(migrated_db: None) -> AsyncIterator[World]:
    """Данные закоммичены по-настоящему, чтобы их видели разные подключения. После теста удаляются."""
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessions() as s:
        team = Team(name=f"Команда {suffix}")
        s.add(team)
        await s.flush()
        anna = User(
            login=f"anna-{suffix}",
            password_hash="x",
            role=Role.USER,
            full_name="Анна",
            telegram_user_id=TG_ANNA,
            team_id=team.id,
        )
        maria = User(
            login=f"maria-{suffix}",
            password_hash="x",
            role=Role.USER,
            full_name="Мария",
            telegram_user_id=TG_MARIA,
            team_id=team.id,
        )
        s.add_all([anna, maria])
        await s.flush()
        payment = RecurringPayment(
            name="Аренда офиса",
            amount=Decimal("50000.00"),
            currency=Currency.RUB,
            period=Period.MONTHLY,
            first_due_date=TODAY + timedelta(days=2),
            created_by=anna.id,
        )
        s.add(payment)
        await s.flush()
        occurrence = PaymentOccurrence(
            recurring_payment_id=payment.id,
            team_id=team.id,
            seq=0,
            due_date=payment.first_due_date,
            amount=payment.amount,
            currency=payment.currency,
        )
        s.add(occurrence)
        await s.commit()
        world = World(sessions, anna.id, maria.id, payment.id, occurrence.id)
        team_id = team.id
    try:
        yield world
    finally:
        async with sessions() as s:
            await s.execute(delete(AuditLog).where(AuditLog.entity_id == world.occurrence_id))
            await s.execute(delete(RecurringPayment).where(RecurringPayment.id == world.payment_id))
            await s.execute(delete(User).where(User.id.in_([world.anna_id, world.maria_id])))
            await s.execute(delete(Team).where(Team.id == team_id))
            await s.commit()
        await engine.dispose()


async def _hold_lock_and_pay(world: World, release: asyncio.Event) -> None:
    """Анна: блокирует период, ждёт сигнала, отмечает оплату и коммитит."""
    async with world.sessions() as s:
        occ = await s.scalar(
            select(PaymentOccurrence).where(PaymentOccurrence.id == world.occurrence_id).with_for_update()
        )
        assert occ is not None
        await release.wait()
        occ.status, occ.paid_date, occ.paid_by, occ.paid_marked_at = OccurrenceStatus.PAID, TODAY, world.anna_id, NOW
        await s.commit()


async def _final_state(world: World) -> tuple[OccurrenceStatus, date | None, uuid.UUID | None]:
    async with world.sessions() as s:
        occ = await s.get(PaymentOccurrence, world.occurrence_id)
        assert occ is not None
        return occ.status, occ.paid_date, occ.paid_by


async def test_panel_second_payer_waits_and_gets_already_paid(world: World) -> None:
    release = asyncio.Event()
    first = asyncio.create_task(_hold_lock_and_pay(world, release))
    await asyncio.sleep(0.2)  # Анна уже держит блокировку

    async def maria_pays() -> AppError | None:
        async with world.sessions() as s:
            maria = await s.get(User, world.maria_id)
            assert maria is not None
            try:
                await update_occurrence(
                    s,
                    world.occurrence_id,
                    new_status=OccurrenceStatus.PAID,
                    paid_date=TODAY - timedelta(days=1),
                    actor=maria,
                    today=TODAY,
                    now=NOW,
                    ip=None,
                )
            except AppError as exc:
                return exc
        return None

    second = asyncio.create_task(maria_pays())
    await asyncio.sleep(0.3)
    assert not second.done()  # Мария ждёт блокировку, а не пишет поверх
    release.set()
    await first
    error = await second

    assert error is not None
    assert (error.status_code, error.code) == (409, "already_paid")
    assert error.detail == "Уже оплачено: Анна, 24.10.2026. Обновите страницу."
    assert await _final_state(world) == (OccurrenceStatus.PAID, TODAY, world.anna_id)


async def test_bot_second_press_waits_and_gets_already_paid(world: World) -> None:
    release = asyncio.Event()
    first = asyncio.create_task(_hold_lock_and_pay(world, release))
    await asyncio.sleep(0.2)

    async def maria_presses() -> tuple[PayResult, uuid.UUID | None]:
        async with world.sessions() as s:
            outcome = await mark_paid_from_telegram(
                s, world.occurrence_id, telegram_user_id=TG_MARIA, today=TODAY + timedelta(days=1), now=NOW
            )
            return outcome.result, outcome.paid_by.id if outcome.paid_by else None

    second = asyncio.create_task(maria_presses())
    await asyncio.sleep(0.3)
    assert not second.done()
    release.set()
    await first

    assert await second == (PayResult.ALREADY_PAID, world.anna_id)
    assert await _final_state(world) == (OccurrenceStatus.PAID, TODAY, world.anna_id)


async def test_two_simultaneous_bot_presses_record_exactly_one_payment(world: World) -> None:
    async def press(telegram_id: int) -> PayResult:
        async with world.sessions() as s:
            outcome = await mark_paid_from_telegram(
                s, world.occurrence_id, telegram_user_id=telegram_id, today=TODAY, now=NOW
            )
            return outcome.result

    anna, maria = await asyncio.gather(press(TG_ANNA), press(TG_MARIA))

    assert {anna, maria} == {PayResult.PAID, PayResult.ALREADY_PAID}
    winner = world.anna_id if anna is PayResult.PAID else world.maria_id
    assert await _final_state(world) == (OccurrenceStatus.PAID, TODAY, winner)
    async with world.sessions() as s:
        actions = (await s.scalars(select(AuditLog.action).where(AuditLog.entity_id == world.occurrence_id))).all()
    assert actions == ["telegram.mark_paid"]  # в журнале одна оплата
