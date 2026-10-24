"""Контракт с веб-панелью (TASK_PLAN §5.4): ответы API совпадают с frontend/src/api/types.ts.

Панель написана против имитации API; если бэкенд вернёт другое имя поля или потеряет поле,
этот тест упадёт раньше, чем это заметят в браузере.
"""

from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from httpx import AsyncClient

from app.domain.enums import (
    Currency,
    NotificationChannel,
    NotificationKind,
    OccurrenceState,
    OccurrenceStatus,
    Period,
    Role,
)
from app.models import User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login
from tests.contract.ts_types import TYPES_TS, interfaces, unions

pytestmark = pytest.mark.skipif(not TYPES_TS.exists(), reason="нет frontend/src/api/types.ts")


def assert_matches(name: str, payload: dict[str, Any]) -> None:
    expected = interfaces()[name]
    keys = set(payload)
    assert expected.required <= keys, f"{name}: нет полей {sorted(expected.required - keys)}"
    assert keys <= expected.fields, f"{name}: лишние поля {sorted(keys - expected.fields)}"


@pytest.mark.parametrize(
    ("ts_name", "enum"),
    [
        ("Currency", Currency),
        ("Role", Role),
        ("OccurrenceStatus", OccurrenceStatus),
        ("OccurrenceState", OccurrenceState),
        ("Channel", NotificationChannel),
        ("NotificationKind", NotificationKind),
        ("Period", Period),
    ],
)
def test_enum_values_match_frontend(ts_name: str, enum: type[StrEnum]) -> None:
    assert unions()[ts_name] == {member.value for member in enum}


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")), tick=False):
        yield


@pytest.fixture
async def tokens(api: AsyncClient, admin: User, regular_user: User) -> dict[str, str]:
    return {"admin": await login(api, ADMIN_LOGIN, ADMIN_PASSWORD), "user": await login(api, USER_LOGIN, USER_PASSWORD)}


@pytest.fixture
async def paid_period(api: AsyncClient, tokens: dict[str, str]) -> dict[str, Any]:
    """Платёж со сроком через день: сразу уходит напоминание, пользователь отмечает оплату."""
    created = await api.post(
        "/api/v1/recurring-payments",
        json={"name": "Аренда", "amount": "50000", "currency": "RUB", "next_due_date": "2026-10-16"},
        headers=bearer(tokens["admin"]),
    )
    assert created.status_code == 201, created.text
    period_id = created.json()["next_occurrence"]["id"]
    paid = await api.patch(
        f"/api/v1/payment-occurrences/{period_id}", json={"status": "paid"}, headers=bearer(tokens["user"])
    )
    assert paid.status_code == 200, paid.text
    result: dict[str, Any] = paid.json()
    return result


async def get(api: AsyncClient, token: str, path: str, **params: Any) -> Any:
    response = await api.get(f"/api/v1{path}", params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


async def test_login_response(api: AsyncClient, regular_user: User) -> None:
    response = await api.post("/api/v1/auth/login", json={"login": USER_LOGIN, "password": USER_PASSWORD})

    assert_matches("LoginResponse", response.json())
    assert_matches("User", response.json()["user"])


async def test_me_and_profile_update(api: AsyncClient, tokens: dict[str, str]) -> None:
    me = await get(api, tokens["user"], "/auth/me")
    updated = await api.patch(
        "/api/v1/auth/me", json={"email": "anna@kefcoders.ru", "notify_email": True}, headers=bearer(tokens["user"])
    )

    assert_matches("Me", me)
    assert_matches("User", me["user"])
    assert_matches("User", updated.json())


async def test_users_page(api: AsyncClient, tokens: dict[str, str]) -> None:
    page = await get(api, tokens["admin"], "/users", limit=200)

    assert_matches("Page", page)
    for user in page["items"]:
        assert_matches("User", user)


async def test_payment_list_and_detail(api: AsyncClient, tokens: dict[str, str], paid_period: dict[str, Any]) -> None:
    page = await get(api, tokens["user"], "/recurring-payments", limit=200)
    detail = await get(api, tokens["user"], f"/recurring-payments/{paid_period['recurring_payment_id']}")

    assert_matches("Page", page)
    assert_matches("RecurringPayment", page["items"][0])
    assert_matches("UserBrief", page["items"][0]["created_by"])
    assert_matches("Occurrence", page["items"][0]["next_occurrence"])
    assert_matches("RecurringPaymentDetail", detail)
    for occurrence in detail["occurrences"]:
        assert_matches("Occurrence", occurrence)


async def test_occurrence_list_and_detail(
    api: AsyncClient, tokens: dict[str, str], paid_period: dict[str, Any]
) -> None:
    page = await get(api, tokens["user"], "/payment-occurrences", sort="-due_date", currency=["RUB", "USD"])
    detail = await get(api, tokens["user"], f"/payment-occurrences/{paid_period['id']}")

    assert_matches("Occurrence", paid_period)
    assert_matches("PaymentBrief", paid_period["recurring_payment"])
    assert_matches("UserBrief", paid_period["paid_by"])
    for occurrence in page["items"]:
        assert_matches("Occurrence", occurrence)
    assert_matches("OccurrenceDetail", detail)
    assert detail["history"] and detail["reminders"]
    for entry in detail["history"]:
        assert_matches("AuditLog", entry)
        assert_matches("UserBrief", entry["actor"])
    for reminder in detail["reminders"]:
        assert_matches("NotificationLog", reminder)


async def test_audit_details_have_keys_used_by_panel_texts(
    api: AsyncClient, tokens: dict[str, str], paid_period: dict[str, Any]
) -> None:
    """frontend/src/lib/audit.ts строит текст события из этих ключей details."""
    detail = await get(api, tokens["user"], f"/payment-occurrences/{paid_period['id']}")

    [mark_paid] = [h for h in detail["history"] if h["action"] == "occurrence.mark_paid"]
    assert set(mark_paid["details"]) == {"payment_name", "due_date", "paid_date"}


async def test_summary(api: AsyncClient, tokens: dict[str, str], paid_period: dict[str, Any]) -> None:
    summary = await get(api, tokens["user"], "/payments/summary", date_from="2026-10-01", date_to="2026-10-31")

    assert_matches("Summary", summary)
    assert set(summary["period"]) == {"from", "to"}
    for total in summary["totals"]:
        assert_matches("CurrencyTotal", total)


async def test_telegram_link_code(api: AsyncClient, tokens: dict[str, str]) -> None:
    response = await api.post("/api/v1/telegram/link-code", headers=bearer(tokens["user"]))

    assert_matches("LinkCode", response.json())


async def test_calendar(api: AsyncClient, tokens: dict[str, str], paid_period: dict[str, Any]) -> None:
    near = await get(api, tokens["user"], "/payments/calendar", month="2026-10")
    far = await get(api, tokens["user"], "/payments/calendar", month="2027-06")

    assert_matches("CalendarMonth", near)
    for day in near["days"] + far["days"]:
        assert_matches("CalendarDay", day)
        for occurrence in day["occurrences"]:
            assert_matches("Occurrence", occurrence)
        for planned in day["planned"]:
            assert_matches("PlannedItem", planned)
    assert any(day["planned"] for day in far["days"])


async def test_budgets(api: AsyncClient, tokens: dict[str, str]) -> None:
    items = [
        {"currency": "RUB", "period_type": "month", "year": 2026, "month": 10, "amount": "90000.00"},
        {"currency": "EUR", "period_type": "year", "year": 2026, "month": None, "amount": "700.00"},
    ]
    saved = await api.put("/api/v1/budgets", json=items, headers=bearer(tokens["admin"]))
    read = await get(api, tokens["user"], "/budgets", year=2026, month=10)

    for budget in saved.json() + read:
        assert_matches("Budget", budget)


# ---------- ошибки: панель различает их по code и показывает detail ----------


@pytest.mark.parametrize(
    ("method", "path", "body", "token_name", "status", "code"),
    [
        ("GET", "/auth/me", None, None, 401, "unauthorized"),
        ("POST", "/auth/login", {"login": USER_LOGIN, "password": "wrong-pass"}, None, 401, "invalid_credentials"),
        ("GET", "/users", None, "user", 403, "forbidden"),
        ("POST", "/users", {"login": "anna", "password": "long-enough"}, "admin", 409, "login_taken"),
        ("DELETE", "/recurring-payments/00000000-0000-0000-0000-000000000000", None, "admin", 404, "not_found"),
        ("POST", "/recurring-payments", {"name": "x"}, "admin", 422, "validation_error"),
        ("PATCH", "/auth/me", {"email": "admin@kefcoders.ru"}, "admin", 403, "system_user"),
    ],
)
async def test_error_shape(
    api: AsyncClient,
    tokens: dict[str, str],
    method: str,
    path: str,
    body: dict[str, Any] | None,
    token_name: str | None,
    status: int,
    code: str,
) -> None:
    api.cookies.clear()  # только явный токен: проверяем и запросы без входа
    headers = bearer(tokens[token_name]) if token_name else {}

    response = await api.request(method, f"/api/v1{path}", json=body, headers=headers)

    assert response.status_code == status
    assert set(response.json()) == {"detail", "code"}
    assert response.json()["code"] == code
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
