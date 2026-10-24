"""Календарь оплат и бюджеты на месяц и год (дополнительные возможности кейса)."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Team, User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")), tick=False):
        yield


@pytest.fixture
async def admin_token(api: AsyncClient, admin: User) -> str:
    return await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)


@pytest.fixture
async def user_token(api: AsyncClient, regular_user: User) -> str:
    return await login(api, USER_LOGIN, USER_PASSWORD)


async def add_payment(api: AsyncClient, token: str, **body: Any) -> dict[str, Any]:
    response = await api.post("/api/v1/recurring-payments", json=body, headers=bearer(token))
    assert response.status_code == 201, response.text
    payment: dict[str, Any] = response.json()
    return payment


async def calendar(api: AsyncClient, token: str, month: str | None = None) -> dict[str, Any]:
    params = {"month": month} if month else {}
    response = await api.get("/api/v1/payments/calendar", params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------- календарь ----------


async def test_calendar_groups_periods_by_day(api: AsyncClient, admin_token: str, user_token: str) -> None:
    await add_payment(api, admin_token, name="Аренда", amount="50000", currency="RUB", next_due_date="2026-10-25")
    await add_payment(api, admin_token, name="Сервер", amount="20", currency="USD", next_due_date="2026-10-25")
    await add_payment(api, admin_token, name="Подписка", amount="9.99", currency="EUR", next_due_date="2026-10-05")

    body = await calendar(api, user_token, "2026-10")

    assert body["month"] == "2026-10"
    assert [d["date"] for d in body["days"]] == ["2026-10-05", "2026-10-25"]
    assert [o["recurring_payment"]["name"] for o in body["days"][1]["occurrences"]] == ["Аренда", "Сервер"]
    assert body["days"][0]["occurrences"][0]["state"] == "overdue"
    assert {d["planned"] == [] for d in body["days"]} == {True}


async def test_far_month_shows_planned_dues_without_created_periods(api: AsyncClient, admin_token: str) -> None:
    payment = await add_payment(
        api, admin_token, name="Аренда", amount="50000", currency="RUB", next_due_date="2026-01-31"
    )

    body = await calendar(api, admin_token, "2027-02")

    [day] = body["days"]
    assert day["date"] == "2027-02-28"  # нет 31-го → последний день месяца
    assert day["occurrences"] == []
    assert day["planned"] == [
        {
            "recurring_payment_id": payment["id"],
            "name": "Аренда",
            "due_date": "2027-02-28",
            "amount": "50000.00",
            "currency": "RUB",
        }
    ]


async def test_stopped_payment_keeps_history_but_has_no_plans(api: AsyncClient, admin_token: str) -> None:
    payment = await add_payment(
        api, admin_token, name="Хостинг", amount="1290", currency="RUB", next_due_date="2026-10-01"
    )
    await api.delete(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(admin_token))

    october = await calendar(api, admin_token, "2026-10")
    next_year = await calendar(api, admin_token, "2027-03")

    assert [d["date"] for d in october["days"]] == ["2026-10-01"]
    assert next_year["days"] == []


async def test_calendar_defaults_to_current_month(api: AsyncClient, admin_token: str) -> None:
    assert (await calendar(api, admin_token))["month"] == "2026-10"


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "октябрь", "2026-10-01"])
async def test_invalid_month_is_rejected(api: AsyncClient, admin_token: str, month: str) -> None:
    response = await api.get("/api/v1/payments/calendar", params={"month": month}, headers=bearer(admin_token))

    assert response.status_code == 422
    assert response.json()["detail"] == "Месяц — в формате ГГГГ-ММ"


# ---------- бюджеты ----------

BUDGETS = [
    {"currency": "RUB", "period_type": "month", "year": 2026, "month": 10, "amount": "90000.00"},
    {"currency": "RUB", "period_type": "year", "year": 2026, "month": None, "amount": "1100000.00"},
    {"currency": "USD", "period_type": "month", "year": 2026, "month": 10, "amount": "250"},
]


@pytest.fixture
def budgets(team: Team) -> list[dict[str, Any]]:
    return [{"team_id": str(team.id), **item} for item in BUDGETS]


async def test_admin_saves_and_everyone_reads_budgets(
    api: AsyncClient, admin_token: str, user_token: str, budgets: list[dict[str, Any]]
) -> None:
    saved = await api.put("/api/v1/budgets", json=budgets, headers=bearer(admin_token))

    read = await api.get("/api/v1/budgets", params={"year": 2026, "month": 10}, headers=bearer(user_token))

    assert saved.status_code == 200
    assert {(b["currency"], b["period_type"], b["amount"]) for b in read.json()} == {
        ("RUB", "month", "90000.00"),
        ("RUB", "year", "1100000.00"),
        ("USD", "month", "250.00"),
    }


async def test_saving_again_updates_instead_of_duplicating(
    api: AsyncClient, admin_token: str, budgets: list[dict[str, Any]]
) -> None:
    await api.put("/api/v1/budgets", json=budgets, headers=bearer(admin_token))
    changed = [{**budgets[0], "amount": "95000"}]

    await api.put("/api/v1/budgets", json=changed, headers=bearer(admin_token))

    read = (await api.get("/api/v1/budgets", params={"year": 2026, "month": 10}, headers=bearer(admin_token))).json()
    rub_month = [b for b in read if b["currency"] == "RUB" and b["period_type"] == "month"]
    assert [b["amount"] for b in rub_month] == ["95000.00"]
    assert len(read) == 3


async def test_other_months_budget_is_not_returned(
    api: AsyncClient, admin_token: str, budgets: list[dict[str, Any]]
) -> None:
    await api.put("/api/v1/budgets", json=budgets, headers=bearer(admin_token))

    november = (
        await api.get("/api/v1/budgets", params={"year": 2026, "month": 11}, headers=bearer(admin_token))
    ).json()

    assert [(b["currency"], b["period_type"]) for b in november] == [("RUB", "year")]


async def test_budget_shows_up_in_month_summary(
    api: AsyncClient, admin_token: str, budgets: list[dict[str, Any]]
) -> None:
    await api.put("/api/v1/budgets", json=budgets, headers=bearer(admin_token))
    await add_payment(api, admin_token, name="Аренда", amount="50000", currency="RUB", next_due_date="2026-10-25")

    summary = await api.get(
        "/api/v1/payments/summary",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
        headers=bearer(admin_token),
    )

    rub = next(t for t in summary.json()["totals"] if t["currency"] == "RUB")
    assert (rub["budget"], rub["budget_left"]) == ("90000.00", "40000.00")


async def test_user_cannot_change_budgets(api: AsyncClient, user_token: str, budgets: list[dict[str, Any]]) -> None:
    response = await api.put("/api/v1/budgets", json=budgets, headers=bearer(user_token))

    assert response.status_code == 403


async def test_budget_change_is_audited(
    api: AsyncClient, admin_token: str, db_session: AsyncSession, budgets: list[dict[str, Any]]
) -> None:
    await api.put("/api/v1/budgets", json=budgets, headers=bearer(admin_token))

    details = await db_session.scalar(select(AuditLog.details).where(AuditLog.action == "budget.update"))

    assert details == {"items": 3}


@pytest.mark.parametrize(
    "item",
    [
        {**BUDGETS[0], "amount": "0"},
        {**BUDGETS[0], "amount": "10.555"},
        {**BUDGETS[0], "month": None},
        {**BUDGETS[1], "month": 5},
        {**BUDGETS[0], "month": 13},
        {**BUDGETS[0], "currency": "GBP"},
    ],
)
async def test_invalid_budget_is_rejected(api: AsyncClient, admin_token: str, item: dict[str, Any], team: Team) -> None:
    response = await api.put("/api/v1/budgets", json=[{"team_id": str(team.id), **item}], headers=bearer(admin_token))

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
