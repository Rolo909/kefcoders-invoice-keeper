"""Напоминание приходит в общий чат, а привязанным пользователям, которых в чате нет, — в личку.
После оплаты (в панели или кнопкой) все копии напоминания становятся «✅ Платёж оплачен»;
если отметку сняли — снова напоминанием с кнопкой.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from aiogram.types import CallbackQuery, Message
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import handlers
from app.db import SessionFactory
from app.domain.enums import Currency, Period, Role
from app.domain.status import today_in
from app.models import PaymentOccurrence, RecurringPayment, TelegramMessage, User
from app.services.notifiers.telegram import TelegramNotifier
from app.services.occurrences import ensure_occurrences
from app.services.reminders import ReminderDispatcher
from app.services.telegram import pay_callback_data
from tests.conftest import USER_LOGIN, USER_PASSWORD, bearer, login

MSK = ZoneInfo("Europe/Moscow")
TODAY = today_in(MSK)
GROUP = -1001234567890
TG_ANNA, TG_MARIA = 555_001, 555_002


@dataclass
class FakeTelegram:
    """Bot API без сети: кто в общем чате, что отправлено и что исправлено."""

    in_group: set[int] = field(default_factory=set)
    blocked: set[int] = field(default_factory=set)  # заблокировали бота — в личку не написать
    sent: list[dict[str, Any]] = field(default_factory=list)
    edited: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content)
        if method == "getChatMember":
            status = "member" if payload["user_id"] in self.in_group else "left"
            return httpx.Response(200, json={"ok": True, "result": {"status": status}})
        if method == "sendMessage":
            chat = int(payload["chat_id"])
            if chat in self.blocked:
                return httpx.Response(200, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
            self.sent.append(payload)
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": len(self.sent), "chat": {"id": chat}}}
            )
        if method == "editMessageText":
            self.edited.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(404, json={"ok": False, "description": method})

    def chats(self) -> list[int]:
        return [int(m["chat_id"]) for m in self.sent]


@pytest.fixture
def fake() -> FakeTelegram:
    return FakeTelegram(in_group={TG_ANNA})


def dispatcher(
    session_factory: SessionFactory, fake: FakeTelegram, group: str | None = str(GROUP)
) -> ReminderDispatcher:
    notifier = TelegramNotifier(
        "123:TOKEN", group, session_factory=session_factory, transport=httpx.MockTransport(fake.handle)
    )
    return ReminderDispatcher(session_factory, [notifier], remind_days_before=3, timezone=MSK)


@pytest.fixture
async def period(db_session: AsyncSession, admin: User, regular_user: User) -> PaymentOccurrence:
    """Аренда со сроком через 2 дня; Анна (в общем чате) и Мария (не в чате) привязали Telegram."""
    regular_user.telegram_user_id = TG_ANNA
    db_session.add(User(login="maria", password_hash="x", role=Role.USER, full_name="Мария", telegram_user_id=TG_MARIA))
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


async def stored(session: AsyncSession) -> list[tuple[int, str | None]]:
    rows = await session.execute(
        select(TelegramMessage.chat_id, User.login).outerjoin(User, User.id == TelegramMessage.user_id)
    )
    return sorted((chat, user) for chat, user in rows)


# ---------- кому приходит напоминание ----------


async def test_group_gets_reminder_and_member_outside_it_gets_dm(
    db_session: AsyncSession, period: PaymentOccurrence, session_factory: SessionFactory, fake: FakeTelegram
) -> None:
    assert await dispatcher(session_factory, fake).run(today=TODAY) == 1

    assert fake.chats() == [GROUP, TG_MARIA]  # Анна в чате — дубля в личку нет
    assert all("✅ Оплачено" in json.dumps(m["reply_markup"], ensure_ascii=False) for m in fake.sent)
    assert await stored(db_session) == [(GROUP, None), (TG_MARIA, "maria")]


async def test_without_group_chat_everyone_linked_gets_dm(
    db_session: AsyncSession, period: PaymentOccurrence, session_factory: SessionFactory, fake: FakeTelegram
) -> None:
    await dispatcher(session_factory, fake, group=None).run(today=TODAY)

    assert sorted(fake.chats()) == [TG_ANNA, TG_MARIA]


async def test_blocked_dm_does_not_break_reminder(
    db_session: AsyncSession, period: PaymentOccurrence, session_factory: SessionFactory, fake: FakeTelegram
) -> None:
    fake.blocked.add(TG_MARIA)

    assert await dispatcher(session_factory, fake).run(today=TODAY) == 1
    assert await stored(db_session) == [(GROUP, None)]


async def test_reminder_is_not_sent_twice_to_anyone(
    db_session: AsyncSession, period: PaymentOccurrence, session_factory: SessionFactory, fake: FakeTelegram
) -> None:
    reminders = dispatcher(session_factory, fake)
    await reminders.run(today=TODAY)

    await reminders.run(today=TODAY)

    assert fake.chats() == [GROUP, TG_MARIA]


# ---------- оплата меняет все копии ----------


async def test_paying_in_panel_turns_every_copy_into_paid(
    app: FastAPI,
    api: AsyncClient,
    db_session: AsyncSession,
    period: PaymentOccurrence,
    session_factory: SessionFactory,
    fake: FakeTelegram,
) -> None:
    reminders = dispatcher(session_factory, fake)
    await reminders.run(today=TODAY)
    app.state.reminders = reminders
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    response = await api.patch(
        f"/api/v1/payment-occurrences/{period.id}", json={"status": "paid"}, headers=bearer(token)
    )

    assert response.status_code == 200
    assert sorted(int(e["chat_id"]) for e in fake.edited) == sorted([GROUP, TG_MARIA])
    for edit in fake.edited:
        assert edit["text"].startswith("✅ Платёж оплачен\n<b>Аренда офиса</b>")
        assert f"Оплатил(а): Анна, {TODAY:%d.%m.%Y}" in edit["text"]
        assert "reply_markup" not in edit  # кнопка «Оплачено» убрана


async def test_unmarking_in_panel_brings_reminder_back(
    app: FastAPI,
    api: AsyncClient,
    db_session: AsyncSession,
    period: PaymentOccurrence,
    session_factory: SessionFactory,
    fake: FakeTelegram,
) -> None:
    reminders = dispatcher(session_factory, fake)
    await reminders.run(today=TODAY)
    app.state.reminders = reminders
    token = await login(api, USER_LOGIN, USER_PASSWORD)
    path = f"/api/v1/payment-occurrences/{period.id}"
    await api.patch(path, json={"status": "paid"}, headers=bearer(token))
    fake.edited.clear()

    await api.patch(path, json={"status": "unpaid"}, headers=bearer(token))

    assert len(fake.edited) == 2
    for edit in fake.edited:
        assert edit["text"].startswith("🔔 Напоминание об оплате\n<b>Аренда офиса</b>")
        assert "✅ Оплачено" in json.dumps(edit["reply_markup"], ensure_ascii=False)


async def test_paid_button_turns_every_copy_into_paid(
    db_session: AsyncSession, period: PaymentOccurrence, session_factory: SessionFactory, fake: FakeTelegram
) -> None:
    reminders = dispatcher(session_factory, fake)
    await reminders.run(today=TODAY)
    message = MagicMock(spec=Message)
    message.chat, message.message_id = MagicMock(id=GROUP), 1
    callback = MagicMock(spec=CallbackQuery)
    callback.data, callback.from_user, callback.message = pay_callback_data(period.id), MagicMock(id=TG_ANNA), message
    callback.answer = AsyncMock()

    await handlers.pay(callback, session_factory, MSK, reminders)

    callback.answer.assert_awaited_once_with("Отмечено как оплаченное")
    assert sorted(int(e["chat_id"]) for e in fake.edited) == sorted([GROUP, TG_MARIA])
    assert all(e["text"].startswith("✅ Платёж оплачен") for e in fake.edited)


async def test_message_sent_before_tracking_is_updated_when_pressed(
    db_session: AsyncSession, period: PaymentOccurrence, session_factory: SessionFactory, fake: FakeTelegram
) -> None:
    # Напоминание ушло до этой версии: в базе его нет, но кнопку нажали — его тоже меняем.
    period.status, period.paid_date = period.status.PAID, TODAY
    await db_session.flush()

    edited = await dispatcher(session_factory, fake).sync_telegram(period.id, pressed=(GROUP, 77))

    assert edited == 1
    assert (int(fake.edited[0]["chat_id"]), fake.edited[0]["message_id"]) == (GROUP, 77)
