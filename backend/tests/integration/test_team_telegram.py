"""Telegram и напоминания по командам: напоминание — в чат команды периода, «Оплачено» — только её участник.

Посторонний в чате, участник другой команды, исключённый из команды и нажатие в чужом чате — отказ,
период остаётся неоплаченным.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import aiosmtplib
import httpx
import pytest
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import handlers
from app.db import SessionFactory
from app.domain.enums import Currency, NotificationKind, OccurrenceStatus, Period, Role
from app.models import AuditLog, PaymentOccurrence, RecurringPayment, Team, User
from app.services.notifiers.base import Reminder, SendResult, TeamTarget
from app.services.notifiers.email import EmailNotifier
from app.services.notifiers.telegram import TelegramNotifier
from app.services.notifiers.webhook import WebhookNotifier
from app.services.occurrences import ensure_occurrences
from app.services.reminders import ReminderDispatcher
from app.services.telegram import PayResult, PressedIn, is_team_chat, mark_paid_from_telegram, migrate_team_chats

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
MSK = ZoneInfo("Europe/Moscow")
KEF_CHAT, STUDIO_CHAT, COMMON_CHAT = -1001000000001, -1001000000002, -1001000000099
TG_ANNA, TG_OLEG, TG_ADMIN = 555_001, 555_002, 555_003


@dataclass
class Teams:
    kef: Team
    studio: Team
    anna: User
    oleg: User
    admin: User
    payment: RecurringPayment  # общий: период у каждой команды

    async def period(self, session: AsyncSession, team: Team) -> PaymentOccurrence:
        found = await session.scalar(
            select(PaymentOccurrence).where(
                PaymentOccurrence.recurring_payment_id == self.payment.id, PaymentOccurrence.team_id == team.id
            )
        )
        assert found is not None
        return found


@pytest.fixture
async def teams(db_session: AsyncSession, team: Team, regular_user: User, admin: User) -> Teams:
    team.telegram_chat_id = str(KEF_CHAT)
    studio = Team(name="Студия дизайна", telegram_chat_id=str(STUDIO_CHAT), created_at=team.created_at)
    db_session.add(studio)
    await db_session.flush()
    oleg = User(login="oleg", password_hash="x", role=Role.USER, full_name="Олег", team_id=studio.id)
    db_session.add(oleg)
    regular_user.telegram_user_id, oleg.telegram_user_id, admin.telegram_user_id = TG_ANNA, TG_OLEG, TG_ADMIN
    payment = RecurringPayment(
        name="Бухгалтерское сопровождение",
        amount=Decimal("25000.00"),
        currency=Currency.RUB,
        period=Period.MONTHLY,
        first_due_date=TODAY + timedelta(days=2),
        created_by=admin.id,
    )
    db_session.add(payment)
    await db_session.flush()
    await ensure_occurrences(db_session, [payment], today=TODAY, horizon_days=10, timezone=MSK)
    return Teams(team, studio, regular_user, oleg, admin, payment)


async def press(
    session: AsyncSession,
    period: PaymentOccurrence,
    telegram_id: int,
    chat: int | None,
    *,
    fallback: str | None = None,
    username: str | None = None,
) -> PayResult:
    outcome = await mark_paid_from_telegram(
        session,
        period.id,
        telegram_user_id=telegram_id,
        pressed_in=None if chat is None else PressedIn(chat, username),
        fallback_chat_id=fallback,
        today=TODAY,
        now=NOW,
    )
    return outcome.result


# ---------- кто может нажать «Оплачено» ----------


async def test_member_pays_in_own_team_chat(db_session: AsyncSession, teams: Teams) -> None:
    period = await teams.period(db_session, teams.kef)

    assert await press(db_session, period, TG_ANNA, KEF_CHAT) is PayResult.PAID
    assert (period.status, period.paid_by) == (OccurrenceStatus.PAID, teams.anna.id)


async def test_member_of_another_team_cannot_pay(db_session: AsyncSession, teams: Teams) -> None:
    # Олег из Студии оказался в чате Kefcoders и нажал кнопку их периода.
    period = await teams.period(db_session, teams.kef)

    outcome = await mark_paid_from_telegram(
        db_session,
        period.id,
        telegram_user_id=TG_OLEG,
        pressed_in=PressedIn(KEF_CHAT),
        fallback_chat_id=None,
        today=TODAY,
        now=NOW,
    )

    assert (outcome.result, outcome.team_name) == (PayResult.NOT_MEMBER, "Kefcoders")
    assert period.status is OccurrenceStatus.UNPAID


async def test_user_removed_from_team_cannot_pay(db_session: AsyncSession, teams: Teams) -> None:
    period = await teams.period(db_session, teams.kef)
    teams.anna.team_id = teams.studio.id  # перевели в другую команду
    await db_session.flush()

    assert await press(db_session, period, TG_ANNA, KEF_CHAT) is PayResult.NOT_MEMBER
    assert period.status is OccurrenceStatus.UNPAID


async def test_stranger_without_linked_account_cannot_pay(db_session: AsyncSession, teams: Teams) -> None:
    period = await teams.period(db_session, teams.kef)

    assert await press(db_session, period, 999_999, KEF_CHAT) is PayResult.NOT_LINKED
    assert period.status is OccurrenceStatus.UNPAID


@pytest.mark.parametrize("chat", [STUDIO_CHAT, COMMON_CHAT, TG_ANNA, None])
async def test_button_pressed_outside_team_chat_is_refused(
    db_session: AsyncSession, teams: Teams, chat: int | None
) -> None:
    # Чат Студии, общий чат, личка с ботом (пересланное сообщение) или неизвестный чат.
    period = await teams.period(db_session, teams.kef)

    assert await press(db_session, period, TG_ANNA, chat, fallback=str(COMMON_CHAT)) is PayResult.WRONG_CHAT
    assert period.status is OccurrenceStatus.UNPAID


async def test_admin_can_pay_in_any_team_chat(db_session: AsyncSession, teams: Teams) -> None:
    period = await teams.period(db_session, teams.studio)

    assert await press(db_session, period, TG_ADMIN, STUDIO_CHAT) is PayResult.PAID
    assert period.paid_by == teams.admin.id


async def test_team_without_own_chat_pays_in_common_chat(db_session: AsyncSession, teams: Teams) -> None:
    teams.studio.telegram_chat_id = None
    period = await teams.period(db_session, teams.studio)

    assert await press(db_session, period, TG_OLEG, STUDIO_CHAT, fallback=str(COMMON_CHAT)) is PayResult.WRONG_CHAT
    assert await press(db_session, period, TG_OLEG, COMMON_CHAT, fallback=str(COMMON_CHAT)) is PayResult.PAID


async def test_in_common_chat_only_period_team_pays(db_session: AsyncSession, teams: Teams) -> None:
    # Обе команды без своего чата: напоминания обеих в общем чате, но чужой период не оплатить.
    teams.kef.telegram_chat_id = teams.studio.telegram_chat_id = None
    period = await teams.period(db_session, teams.studio)

    assert await press(db_session, period, TG_ANNA, COMMON_CHAT, fallback=str(COMMON_CHAT)) is PayResult.NOT_MEMBER
    assert period.status is OccurrenceStatus.UNPAID


def test_public_group_is_matched_by_username() -> None:
    assert is_team_chat("@Design_Team", PressedIn(-100777, "design_team"))
    assert not is_team_chat("@design_team", PressedIn(-100777, None))
    assert not is_team_chat("-100777", PressedIn(-100778))
    assert not is_team_chat(None, PressedIn(-100777))


# ---------- обработчики ----------


def callback(occurrence_id: uuid.UUID, telegram_id: int, chat_id: int) -> MagicMock:
    message = MagicMock(spec=Message)
    message.chat = SimpleNamespace(id=chat_id, username=None)
    message.html_text = "🔔 <b>Бухгалтерское сопровождение</b>"
    message.edit_text = AsyncMock()
    pressed = MagicMock()
    pressed.data = f"pay:{occurrence_id}"
    pressed.from_user = SimpleNamespace(id=telegram_id)
    pressed.message = message
    pressed.answer = AsyncMock()
    return pressed


async def test_outsider_sees_refusal_and_message_stays_open(
    db_session: AsyncSession, teams: Teams, session_factory: SessionFactory
) -> None:
    period = await teams.period(db_session, teams.kef)
    pressed = callback(period.id, TG_OLEG, KEF_CHAT)

    await handlers.pay(pressed, session_factory, MSK, None)

    pressed.answer.assert_awaited_once_with(
        "Отмечать оплату могут только участники команды «Kefcoders». Обратитесь к администратору.", show_alert=True
    )
    pressed.message.edit_text.assert_not_awaited()  # кнопка остаётся для участников команды


async def test_wrong_chat_refusal_names_team(
    db_session: AsyncSession, teams: Teams, session_factory: SessionFactory
) -> None:
    period = await teams.period(db_session, teams.kef)
    pressed = callback(period.id, TG_ANNA, STUDIO_CHAT)

    await handlers.pay(pressed, session_factory, MSK, None)

    pressed.answer.assert_awaited_once_with(
        "Эта кнопка из другого чата. Отметьте оплату в чате команды «Kefcoders» или в панели.", show_alert=True
    )


async def test_chatid_command_shows_chat_id() -> None:
    message = MagicMock(spec=Message)
    message.chat = SimpleNamespace(id=KEF_CHAT)
    message.answer = AsyncMock()

    await handlers.chat_id(message)

    assert f"<code>{KEF_CHAT}</code>" in message.answer.call_args.args[0]


async def test_group_upgraded_to_supergroup_keeps_team_chat(
    db_session: AsyncSession, teams: Teams, session_factory: SessionFactory
) -> None:
    message = MagicMock(spec=Message)
    message.chat = SimpleNamespace(id=KEF_CHAT)
    message.migrate_to_chat_id = -1009999999999

    await handlers.chat_migrated(message, session_factory)

    assert teams.kef.telegram_chat_id == "-1009999999999"
    assert teams.studio.telegram_chat_id == str(STUDIO_CHAT)
    log = await db_session.scalar(select(AuditLog).where(AuditLog.action == "team.update"))
    assert log is not None
    assert (log.actor_login, log.details["reason"]) == ("telegram", "chat_migrated")


async def test_migration_of_unknown_chat_changes_nothing(db_session: AsyncSession, teams: Teams) -> None:
    assert await migrate_team_chats(db_session, -1005555, -1006666) == []


# ---------- напоминания по командам ----------


def telegram_capture() -> tuple[httpx.MockTransport, list[dict[str, object]]]:
    sent: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

    return httpx.MockTransport(handle), sent


async def test_each_team_is_reminded_in_its_own_chat(
    db_session: AsyncSession, teams: Teams, session_factory: SessionFactory
) -> None:
    transport, sent = telegram_capture()
    notifier = TelegramNotifier("123:TOKEN", str(COMMON_CHAT), transport=transport)
    dispatcher = ReminderDispatcher(session_factory, [notifier], remind_days_before=3, timezone=MSK)

    assert await dispatcher.run(today=TODAY) == 2

    chats = {(message["chat_id"], str(message["text"]).split("\n")[2]) for message in sent}
    assert chats == {(str(KEF_CHAT), "Команда: Kefcoders"), (str(STUDIO_CHAT), "Команда: Студия дизайна")}


async def test_team_without_chat_is_reminded_in_common_chat(
    db_session: AsyncSession, teams: Teams, session_factory: SessionFactory
) -> None:
    teams.studio.telegram_chat_id = None
    transport, sent = telegram_capture()
    notifier = TelegramNotifier("123:TOKEN", str(COMMON_CHAT), transport=transport)

    await ReminderDispatcher(session_factory, [notifier], remind_days_before=3, timezone=MSK).run(today=TODAY)

    assert sorted(str(m["chat_id"]) for m in sent) == sorted([str(KEF_CHAT), str(COMMON_CHAT)])


async def test_reminder_waits_until_team_chat_is_set(db_session: AsyncSession, teams: Teams) -> None:
    team = TeamTarget(id=teams.studio.id, name="Студия дизайна", telegram_chat_id=None)
    reminder = Reminder(
        occurrence_id=uuid.uuid4(),
        team=team,
        kind=NotificationKind.BEFORE_DUE,
        payment_name="Аренда",
        amount=Decimal(1),
        currency=Currency.RUB,
        due_date=TODAY,
        today=TODAY,
    )

    result = await TelegramNotifier("123:TOKEN", None).send(reminder)

    assert result == SendResult(
        ok=False,
        error="У команды «Студия дизайна» не задан Telegram-чат, и общего TELEGRAM_CHAT_ID в .env нет",
        attempted=False,
    )


async def test_email_goes_only_to_members_of_period_team(
    db_session: AsyncSession, teams: Teams, session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(aiosmtplib, "send", send)
    teams.anna.email, teams.anna.notify_email = "anna@kefcoders.ru", True
    teams.oleg.email, teams.oleg.notify_email = "oleg@studio.ru", True
    await db_session.flush()
    notifier = EmailNotifier(session_factory, host="mailpit", port=1025, sender="keeper@kefcoders.ru")
    target = TeamTarget(id=teams.studio.id, name="Студия дизайна", telegram_chat_id=None)

    recipients = await notifier.recipients(target)

    assert recipients == ["oleg@studio.ru"]


async def test_webhook_payload_names_team() -> None:
    captured: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200)

    team_id = uuid.uuid4()
    reminder = Reminder(
        occurrence_id=uuid.uuid4(),
        team=TeamTarget(id=team_id, name="Студия дизайна", telegram_chat_id=None),
        kind=NotificationKind.BEFORE_DUE,
        payment_name="Аренда",
        amount=Decimal(1),
        currency=Currency.RUB,
        due_date=TODAY,
        today=TODAY,
    )

    await WebhookNotifier("https://hooks.example.com/ik", transport=httpx.MockTransport(handle)).send(reminder)

    assert captured[0]["team"] == {"id": str(team_id), "name": "Студия дизайна"}
