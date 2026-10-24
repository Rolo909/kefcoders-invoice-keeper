"""Дополнительные каналы: почта (SMTP), webhook и колокольчик в панели (TASK_PLAN §7)."""

import json
import uuid
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import aiosmtplib
import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import SessionFactory
from app.domain.enums import Currency, NotificationChannel, NotificationKind
from app.models import Notification, User
from app.services.notifiers.base import Reminder, TeamTarget
from app.services.notifiers.email import NO_RECIPIENTS, EmailNotifier
from app.services.notifiers.inapp import InAppNotifier
from app.services.notifiers.webhook import SIGNATURE_HEADER, WebhookNotifier, signature
from app.services.reminders import ReminderDispatcher, build_notifiers
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login

REMINDER = Reminder(
    occurrence_id=uuid.uuid4(),
    team=TeamTarget(id=uuid.uuid4(), name="Kefcoders", telegram_chat_id=None),
    kind=NotificationKind.BEFORE_DUE,
    payment_name="Аренда офиса",
    amount=Decimal("50000.00"),
    currency=Currency.RUB,
    due_date=date(2026, 10, 26),
    today=date(2026, 10, 24),
)


# ---------- почта ----------


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(aiosmtplib, "send", send)
    return send


def email_notifier(session_factory: SessionFactory, extra: list[str] | None = None) -> EmailNotifier:
    return EmailNotifier(
        session_factory, host="mailpit", port=1025, sender="keeper@kefcoders.ru", extra_recipients=extra
    )


async def test_email_goes_to_users_with_notifications_and_extra_addresses(
    db_session: AsyncSession, regular_user: User, session_factory: SessionFactory, smtp: AsyncMock
) -> None:
    regular_user.email, regular_user.notify_email = "anna@kefcoders.ru", True
    db_session.add(
        User(login="maria", password_hash="x", role="user", email="maria@kefcoders.ru", team_id=regular_user.team_id)
    )
    await db_session.flush()

    own_team = TeamTarget(id=regular_user.team_id, name="Kefcoders", telegram_chat_id=None)  # type: ignore[arg-type]
    notifier = email_notifier(session_factory, ["boss@kefcoders.ru", "anna@kefcoders.ru"])
    result = await notifier.send(replace(REMINDER, team=own_team))

    assert result.ok
    message, kwargs = smtp.call_args.args[0], smtp.call_args.kwargs
    assert kwargs["recipients"] == ["anna@kefcoders.ru", "boss@kefcoders.ru"]  # maria письма не включала
    assert message["To"] == "keeper@kefcoders.ru"  # адреса получателей друг другу не видны
    assert message["Subject"] == "Оплата «Аренда офиса»: 50 000,00 RUB до 26.10.2026"
    assert "Аренда офиса" in message.get_body(preferencelist=("plain",)).get_content()


async def test_email_without_recipients_waits_without_burning_attempts(
    session_factory: SessionFactory, smtp: AsyncMock
) -> None:
    result = await email_notifier(session_factory).send(REMINDER)

    assert (result.ok, result.attempted, result.error) == (False, False, NO_RECIPIENTS)
    smtp.assert_not_awaited()


async def test_smtp_failure_is_reported(session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=aiosmtplib.SMTPConnectError("refused")))

    result = await email_notifier(session_factory, ["boss@kefcoders.ru"]).send(REMINDER)

    assert not result.ok
    assert result.error is not None
    assert result.error.startswith("Почтовый сервер недоступен")


# ---------- webhook ----------


def capture(status_code: int = 200) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code)

    return httpx.MockTransport(handle), requests


async def test_webhook_posts_signed_reminder() -> None:
    transport, requests = capture()

    result = await WebhookNotifier("https://hooks.example.com/ik", "s3cret", transport=transport).send(REMINDER)

    assert result.ok
    body = json.loads(requests[0].content)
    assert body["event"] == "payment.reminder"
    assert body["occurrence"] == {
        "id": str(REMINDER.occurrence_id),
        "due_date": "2026-10-26",
        "amount": "50000.00",
        "currency": "RUB",
    }
    assert body["payment"] == {"name": "Аренда офиса"}
    assert requests[0].headers[SIGNATURE_HEADER] == signature(requests[0].content, "s3cret")


async def test_webhook_without_secret_is_not_signed() -> None:
    transport, requests = capture()

    await WebhookNotifier("https://hooks.example.com/ik", transport=transport).send(REMINDER)

    assert SIGNATURE_HEADER not in requests[0].headers


async def test_webhook_error_status_is_a_failure() -> None:
    transport, _ = capture(500)

    result = await WebhookNotifier("https://hooks.example.com/ik", transport=transport).send(REMINDER)

    assert (result.ok, result.error) == (False, "Webhook ответил кодом 500")


async def test_webhook_network_error_does_not_reveal_url() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    url = "https://hooks.example.com/ik?key=private"
    result = await WebhookNotifier(url, transport=httpx.MockTransport(fail)).send(REMINDER)

    assert not result.ok
    assert result.error is not None
    assert "private" not in result.error


# ---------- набор каналов ----------


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"database_url": "postgresql+asyncpg://u:p@db/x", "admin_password": "long-enough"}
    return Settings(_env_file=None, **base | overrides)


def test_channels_follow_settings(session_factory: SessionFactory) -> None:
    every = build_notifiers(settings(email_enabled=True, webhook_url="https://hooks.example.com/ik"), session_factory)
    minimal = build_notifiers(settings(telegram_enabled=False, inapp_enabled=False), session_factory)

    assert [n.channel for n in every] == list(NotificationChannel)
    assert minimal == []


# ---------- колокольчик ----------


@pytest.fixture
async def inapp_api(
    app: FastAPI, api: AsyncClient, session_factory: SessionFactory, admin: User, regular_user: User
) -> AsyncClient:
    app.state.reminders = ReminderDispatcher(
        session_factory, [InAppNotifier()], remind_days_before=3, timezone=ZoneInfo("Europe/Moscow")
    )
    return api


async def create_due_tomorrow(api: AsyncClient, token: str, name: str = "Бухгалтерия") -> None:
    due = (date.today() + timedelta(days=1)).isoformat()
    response = await api.post(
        "/api/v1/recurring-payments",
        json={"name": name, "amount": "25000", "currency": "RUB", "next_due_date": due},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text


async def test_bell_shows_reminder_and_read_state_is_personal(inapp_api: AsyncClient) -> None:
    admin_token = await login(inapp_api, ADMIN_LOGIN, ADMIN_PASSWORD)
    anna_token = await login(inapp_api, USER_LOGIN, USER_PASSWORD)
    await create_due_tomorrow(inapp_api, admin_token)

    anna = (await inapp_api.get("/api/v1/inbox", headers=bearer(anna_token))).json()
    [item] = anna["items"]
    await inapp_api.post(f"/api/v1/inbox/{item['id']}/read", headers=bearer(anna_token))

    anna_after = (await inapp_api.get("/api/v1/inbox", headers=bearer(anna_token))).json()
    admin_view = (await inapp_api.get("/api/v1/inbox", headers=bearer(admin_token))).json()
    assert (anna["unread_count"], item["payment_name"], item["occurrence_state"]) == (
        1,
        "Бухгалтерия",
        "due_soon",
    )
    assert (anna_after["unread_count"], anna_after["items"][0]["read"]) == (0, True)
    assert (admin_view["unread_count"], admin_view["items"][0]["read"]) == (1, False)


async def test_read_all_and_unread_filter(inapp_api: AsyncClient) -> None:
    admin_token = await login(inapp_api, ADMIN_LOGIN, ADMIN_PASSWORD)
    await create_due_tomorrow(inapp_api, admin_token, "Бухгалтерия")
    await create_due_tomorrow(inapp_api, admin_token, "Интернет")

    before = (await inapp_api.get("/api/v1/inbox", params={"unread_only": True}, headers=bearer(admin_token))).json()
    await inapp_api.post("/api/v1/inbox/read-all", headers=bearer(admin_token))
    after = (await inapp_api.get("/api/v1/inbox", params={"unread_only": True}, headers=bearer(admin_token))).json()

    assert (len(before["items"]), before["unread_count"]) == (2, 2)
    assert (after["items"], after["unread_count"]) == ([], 0)


async def test_repeated_check_does_not_duplicate_bell_notification(
    inapp_api: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    admin_token = await login(inapp_api, ADMIN_LOGIN, ADMIN_PASSWORD)
    await create_due_tomorrow(inapp_api, admin_token)

    await app.state.reminders.run()
    await app.state.reminders.run()

    count = await db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.channel == NotificationChannel.INAPP)
    )
    assert count == 1


async def test_unknown_notification_cannot_be_marked_read(inapp_api: AsyncClient) -> None:
    token = await login(inapp_api, USER_LOGIN, USER_PASSWORD)

    response = await inapp_api.post(f"/api/v1/inbox/{uuid.uuid4()}/read", headers=bearer(token))

    assert response.status_code == 404


# ---------- «Тестовое сообщение» ----------


async def test_channel_check_reports_every_channel(api: AsyncClient, admin: User) -> None:
    token = await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)

    response = await api.post("/api/v1/notifications/test", headers=bearer(token))

    channels = {c["channel"]: (c["ok"], c["error"]) for c in response.json()["channels"]}
    assert channels == {
        "telegram": (True, None),  # в тестах вместо Telegram — записывающий отправщик
        "email": (False, "Канал выключен: EMAIL_ENABLED=false"),
        "webhook": (False, "WEBHOOK_URL не задан"),
        "inapp": (False, "Канал выключен: INAPP_ENABLED=false"),
    }


async def test_channel_check_is_for_admin_only(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    assert (await api.post("/api/v1/notifications/test", headers=bearer(token))).status_code == 403
