"""Привязка Telegram по коду и кнопка «✅ Оплачено» (ARCHITECTURE.md §6)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.enums import ChatType
from aiogram.filters import CommandObject
from aiogram.types import CallbackQuery, Message
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import handlers
from app.db import SessionFactory
from app.domain.enums import Currency, OccurrenceStatus, Period
from app.models import AuditLog, PaymentOccurrence, RecurringPayment, User
from app.services.occurrences import ensure_occurrences
from app.services.telegram import (
    LinkResult,
    PayResult,
    create_link_code,
    link_account,
    mark_paid_from_telegram,
    pay_callback_data,
)
from tests.conftest import USER_LOGIN, USER_PASSWORD, bearer, login

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
TODAY = date(2026, 10, 24)
TG_ANNA = 555_001
TG_STRANGER = 555_999


@pytest.fixture
async def period(db_session: AsyncSession, admin: User) -> PaymentOccurrence:
    payment = RecurringPayment(
        name="Аренда офиса",
        amount=Decimal("50000.00"),
        currency=Currency.RUB,
        period=Period.MONTHLY,
        first_due_date=TODAY + timedelta(days=2),
        created_by=admin.id,
    )
    db_session.add(payment)
    await db_session.flush()
    await ensure_occurrences(db_session, [payment], today=TODAY, horizon_days=10)
    found = await db_session.scalar(
        select(PaymentOccurrence).where(PaymentOccurrence.recurring_payment_id == payment.id)
    )
    assert found is not None
    return found


@pytest.fixture
async def linked_user(db_session: AsyncSession, regular_user: User) -> User:
    link = await create_link_code(db_session, regular_user, now=NOW)
    outcome = await link_account(db_session, link.code, telegram_user_id=TG_ANNA, now=NOW)
    assert outcome.result is LinkResult.LINKED
    return regular_user


# ---------- коды и привязка ----------


async def test_link_code_has_six_digits_and_lives_ten_minutes(db_session: AsyncSession, regular_user: User) -> None:
    link = await create_link_code(db_session, regular_user, now=NOW)

    assert link.code.isdigit()
    assert len(link.code) == 6
    assert link.expires_at == NOW + timedelta(minutes=10)


async def test_new_code_cancels_previous_one(db_session: AsyncSession, regular_user: User) -> None:
    first = (await create_link_code(db_session, regular_user, now=NOW)).code
    second = (await create_link_code(db_session, regular_user, now=NOW)).code

    assert (await link_account(db_session, first, telegram_user_id=TG_ANNA, now=NOW)).result is LinkResult.INVALID_CODE
    assert (await link_account(db_session, second, telegram_user_id=TG_ANNA, now=NOW)).result is LinkResult.LINKED


async def test_code_links_telegram_once(db_session: AsyncSession, regular_user: User) -> None:
    code = (await create_link_code(db_session, regular_user, now=NOW)).code

    first = await link_account(db_session, code, telegram_user_id=TG_ANNA, now=NOW)
    again = await link_account(db_session, code, telegram_user_id=TG_STRANGER, now=NOW)

    assert (first.result, again.result) == (LinkResult.LINKED, LinkResult.INVALID_CODE)
    assert regular_user.telegram_user_id == TG_ANNA
    assert regular_user.telegram_linked


async def test_expired_or_wrong_code_is_rejected(db_session: AsyncSession, regular_user: User) -> None:
    code = (await create_link_code(db_session, regular_user, now=NOW)).code

    expired = await link_account(db_session, code, telegram_user_id=TG_ANNA, now=NOW + timedelta(minutes=11))
    wrong = await link_account(
        db_session, "000000" if code != "000000" else "111111", telegram_user_id=TG_ANNA, now=NOW
    )

    assert (expired.result, wrong.result) == (LinkResult.INVALID_CODE, LinkResult.INVALID_CODE)


async def test_telegram_moves_to_the_last_linked_account(
    db_session: AsyncSession, linked_user: User, admin: User
) -> None:
    code = (await create_link_code(db_session, admin, now=NOW)).code

    await link_account(db_session, code, telegram_user_id=TG_ANNA, now=NOW)
    await db_session.refresh(linked_user)

    assert (admin.telegram_user_id, linked_user.telegram_user_id) == (TG_ANNA, None)


async def test_link_code_endpoint_and_telegram_linked_flag(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    response = await api.post("/api/v1/telegram/link-code", headers=bearer(token))

    assert response.status_code == 200
    assert set(response.json()) == {"code", "expires_at"}
    assert (await api.get("/api/v1/auth/me", headers=bearer(token))).json()["user"]["telegram_linked"] is False


# ---------- отметка оплаты ----------


async def test_button_marks_period_paid_by_linked_user(
    db_session: AsyncSession, linked_user: User, period: PaymentOccurrence
) -> None:
    outcome = await mark_paid_from_telegram(db_session, period.id, telegram_user_id=TG_ANNA, today=TODAY, now=NOW)

    assert (outcome.result, outcome.paid_date) == (PayResult.PAID, TODAY)
    assert (period.status, period.paid_date, period.paid_by) == (OccurrenceStatus.PAID, TODAY, linked_user.id)
    log = await db_session.scalar(select(AuditLog).where(AuditLog.action == "telegram.mark_paid"))
    assert log is not None
    assert (log.actor_login, log.details["payment_name"], log.details["paid_date"]) == (
        USER_LOGIN,
        "Аренда офиса",
        "2026-10-24",
    )


async def test_second_press_keeps_original_payment_date(
    db_session: AsyncSession, linked_user: User, period: PaymentOccurrence
) -> None:
    await mark_paid_from_telegram(db_session, period.id, telegram_user_id=TG_ANNA, today=TODAY, now=NOW)

    outcome = await mark_paid_from_telegram(
        db_session, period.id, telegram_user_id=TG_ANNA, today=TODAY + timedelta(days=1), now=NOW
    )

    assert (outcome.result, outcome.paid_date, period.paid_date) == (PayResult.ALREADY_PAID, TODAY, TODAY)


async def test_unlinked_telegram_cannot_mark_payment(db_session: AsyncSession, period: PaymentOccurrence) -> None:
    outcome = await mark_paid_from_telegram(db_session, period.id, telegram_user_id=TG_STRANGER, today=TODAY, now=NOW)

    assert outcome.result is PayResult.NOT_LINKED
    assert period.status is OccurrenceStatus.UNPAID


async def test_removed_period_is_reported(db_session: AsyncSession, linked_user: User) -> None:
    outcome = await mark_paid_from_telegram(db_session, uuid.uuid4(), telegram_user_id=TG_ANNA, today=TODAY, now=NOW)

    assert outcome.result is PayResult.NOT_FOUND


# ---------- обработчики бота ----------


def fake_message(*, chat_type: ChatType = ChatType.PRIVATE, user_id: int = TG_ANNA, html_text: str = "") -> MagicMock:
    message = MagicMock(spec=Message)
    message.chat = SimpleNamespace(type=chat_type)
    message.from_user = SimpleNamespace(id=user_id)
    message.html_text = html_text
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    return message


def fake_callback(data: str, *, user_id: int = TG_ANNA, html_text: str = "") -> MagicMock:
    callback = MagicMock(spec=CallbackQuery)
    callback.data = data
    callback.from_user = SimpleNamespace(id=user_id)
    callback.message = fake_message(html_text=html_text)
    callback.answer = AsyncMock()
    return callback


def link_command(code: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="link", args=code)


async def test_start_explains_how_to_link() -> None:
    message = fake_message()

    await handlers.start(message)

    assert "/link" in message.answer.call_args.args[0]


async def test_link_in_group_chat_is_refused(session_factory: SessionFactory) -> None:
    message = fake_message(chat_type=ChatType.SUPERGROUP)

    await handlers.link(message, link_command("123456"), session_factory)

    message.answer.assert_awaited_once_with(handlers.LINK_IN_PRIVATE)


async def test_link_without_code_shows_usage(session_factory: SessionFactory) -> None:
    message = fake_message()

    await handlers.link(message, link_command(None), session_factory)

    message.answer.assert_awaited_once_with(handlers.LINK_USAGE)


async def test_link_command_links_account(
    db_session: AsyncSession, regular_user: User, session_factory: SessionFactory
) -> None:
    code = (await create_link_code(db_session, regular_user, now=datetime.now(UTC))).code
    message = fake_message()

    await handlers.link(message, link_command(code), session_factory)

    assert "Готово" in message.answer.call_args.args[0]
    assert regular_user.telegram_user_id == TG_ANNA


async def test_pay_button_marks_paid_and_closes_message(
    linked_user: User, period: PaymentOccurrence, session_factory: SessionFactory
) -> None:
    callback = fake_callback(pay_callback_data(period.id), html_text="🔔 Напоминание об оплате\n<b>Аренда офиса</b>")

    await handlers.pay(callback, session_factory, ZoneInfo("Europe/Moscow"))

    callback.answer.assert_awaited_once_with("Отмечено как оплаченное")
    edited = callback.message.edit_text.call_args
    assert edited.args[0].endswith("✅ Оплачено: Анна, " + period.paid_date.strftime("%d.%m.%Y"))  # type: ignore[union-attr]
    assert edited.kwargs["reply_markup"] is None


async def test_pay_button_of_unlinked_user_shows_alert(
    period: PaymentOccurrence, session_factory: SessionFactory
) -> None:
    callback = fake_callback(pay_callback_data(period.id), user_id=TG_STRANGER)

    await handlers.pay(callback, session_factory, ZoneInfo("Europe/Moscow"))

    callback.answer.assert_awaited_once_with(handlers.NOT_LINKED, show_alert=True)
    callback.message.edit_text.assert_not_awaited()


async def test_broken_button_data_is_handled(session_factory: SessionFactory) -> None:
    callback = fake_callback("pay:not-a-uuid")

    await handlers.pay(callback, session_factory, ZoneInfo("Europe/Moscow"))

    callback.answer.assert_awaited_once_with(handlers.STALE_BUTTON, show_alert=True)


async def test_second_member_sees_who_already_paid(
    db_session: AsyncSession, linked_user: User, admin: User, period: PaymentOccurrence, session_factory: SessionFactory
) -> None:
    code = (await create_link_code(db_session, admin, now=NOW)).code
    await link_account(db_session, code, telegram_user_id=TG_STRANGER, now=NOW)
    first = fake_callback(pay_callback_data(period.id), user_id=TG_ANNA, html_text="🔔 <b>Аренда офиса</b>")
    second = fake_callback(pay_callback_data(period.id), user_id=TG_STRANGER, html_text="🔔 <b>Аренда офиса</b>")

    await handlers.pay(first, session_factory, ZoneInfo("Europe/Moscow"))
    await handlers.pay(second, session_factory, ZoneInfo("Europe/Moscow"))

    paid_on = period.paid_date.strftime("%d.%m.%Y")  # type: ignore[union-attr]
    second.answer.assert_awaited_once_with(
        f"Уже оплачено: Анна, {paid_on}. Повторно оплачивать не нужно.", show_alert=True
    )
    # Сообщение подписано тем, кто оплатил, а не тем, кто нажал вторым.
    assert second.message.edit_text.call_args.args[0].endswith(f"✅ Оплачено: Анна, {paid_on}")
    assert period.paid_by == linked_user.id
