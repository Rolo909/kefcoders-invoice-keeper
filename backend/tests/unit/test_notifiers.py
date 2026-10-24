import json
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.domain.enums import Currency, NotificationKind
from app.services.notifiers.base import Reminder
from app.services.notifiers.formatting import format_money, plural_days, reminder_text_html
from app.services.notifiers.telegram import TelegramNotifier

TOKEN = "123456:SECRET-TOKEN"


def reminder(**overrides: object) -> Reminder:
    values: dict[str, object] = {
        "occurrence_id": uuid.uuid4(),
        "kind": NotificationKind.BEFORE_DUE,
        "payment_name": "Аренда офиса",
        "amount": Decimal("50000.00"),
        "currency": Currency.RUB,
        "due_date": date(2026, 10, 25),
        "today": date(2026, 10, 23),
    } | overrides
    return Reminder(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 день"),
        (2, "2 дня"),
        (4, "4 дня"),
        (5, "5 дней"),
        (11, "11 дней"),
        (14, "14 дней"),
        (21, "21 день"),
        (22, "22 дня"),
        (111, "111 дней"),
    ],
)
def test_days_are_declined_in_russian(count: int, text: str) -> None:
    assert plural_days(count) == text


def test_money_has_thin_groups_and_comma() -> None:
    assert format_money(Decimal("50000.5")) == "50 000,50"
    assert format_money(Decimal("9.99")) == "9,99"


def test_reminder_contains_name_amount_currency_and_date() -> None:
    text = reminder_text_html(reminder())

    assert "<b>Аренда офиса</b>" in text
    assert "50 000,00 RUB" in text
    assert "25.10.2026 (через 2 дня)" in text


@pytest.mark.parametrize(("today", "when"), [(date(2026, 10, 25), "сегодня"), (date(2026, 10, 24), "завтра")])
def test_reminder_says_today_and_tomorrow(today: date, when: str) -> None:
    assert f"({when})" in reminder_text_html(reminder(today=today))


def test_overdue_text_says_how_late() -> None:
    text = reminder_text_html(reminder(kind=NotificationKind.OVERDUE, today=date(2026, 10, 26)))

    assert text.startswith("⚠️ Просрочена оплата")
    assert "просрочено на 1 день" in text


def test_payment_name_is_escaped_for_html() -> None:
    assert "<b>Сервер &lt;prod&gt; &amp; БД</b>" in reminder_text_html(reminder(payment_name="Сервер <prod> & БД"))


def mock_transport(
    **response: object,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handle), requests


async def test_telegram_sends_html_message_to_configured_chat() -> None:
    transport, requests = mock_transport(ok=True, result={"message_id": 77})
    notifier = TelegramNotifier(TOKEN, "-100500", transport=transport)

    result = await notifier.send(reminder())

    assert (result.ok, result.telegram_message_id) == (True, 77)
    assert requests[0].url.path == f"/bot{TOKEN}/sendMessage"
    payload = json.loads(requests[0].content)
    assert (payload["chat_id"], payload["parse_mode"]) == ("-100500", "HTML")
    assert "Аренда офиса" in payload["text"]


async def test_telegram_api_error_is_reported() -> None:
    transport, _ = mock_transport(ok=False, description="Bad Request: chat not found")

    result = await TelegramNotifier(TOKEN, "-1", transport=transport).send(reminder())

    assert not result.ok
    assert result.error == "Telegram отклонил сообщение: Bad Request: chat not found"


async def test_network_error_never_reveals_bot_token() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    result = await TelegramNotifier(TOKEN, "-1", transport=httpx.MockTransport(fail)).send(reminder())

    assert not result.ok
    assert result.attempted
    assert result.error is not None
    assert TOKEN not in result.error


@pytest.mark.parametrize(("token", "chat"), [(None, "-1"), (TOKEN, None)])
async def test_missing_settings_do_not_count_as_attempt(token: str | None, chat: str | None) -> None:
    result = await TelegramNotifier(token, chat).send(reminder())

    assert (result.ok, result.attempted) == (False, False)
    assert result.error is not None
    assert "TELEGRAM_BOT_TOKEN" in result.error
