"""Итоги по валютам: критерий приёмки «RUB, USD и EUR; итоги считаются отдельно по каждой валюте»."""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import BudgetPeriodType, Currency
from app.models import Budget, User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, bearer, login

OCTOBER = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")), tick=False):
        yield


@pytest.fixture
async def token(api: AsyncClient, admin: User) -> str:
    return await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)


async def add_payment(api: AsyncClient, token: str, **body: Any) -> dict[str, Any]:
    response = await api.post("/api/v1/recurring-payments", json=body, headers=bearer(token))
    assert response.status_code == 201, response.text
    payment: dict[str, Any] = response.json()
    return payment


async def pay(api: AsyncClient, token: str, payment: dict[str, Any], paid_date: str) -> None:
    period_id = payment["next_occurrence"]["id"]
    response = await api.patch(
        f"/api/v1/payment-occurrences/{period_id}",
        json={"status": "paid", "paid_date": paid_date},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text


async def summary(api: AsyncClient, token: str, **params: str) -> dict[str, Any]:
    response = await api.get("/api/v1/payments/summary", params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def by_currency(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["currency"]: t for t in body["totals"]}


@pytest.fixture
async def october(api: AsyncClient, token: str) -> None:
    """Аренда в рублях, сервер в долларах, подписка в евро — как в тестовых данных кейса."""
    await add_payment(api, token, name="Аренда", amount="50000", currency="RUB", next_due_date="2026-10-25")
    domain = await add_payment(api, token, name="Домен", amount="1500", currency="RUB", next_due_date="2026-10-03")
    await pay(api, token, domain, "2026-10-03")
    await add_payment(api, token, name="Сервер", amount="20", currency="USD", next_due_date="2026-10-05")
    figma = await add_payment(api, token, name="Подписка", amount="9.99", currency="EUR", next_due_date="2026-10-10")
    await pay(api, token, figma, "2026-10-12")


async def test_all_three_currencies_are_present_even_without_payments(api: AsyncClient, token: str) -> None:
    body = await summary(api, token, **OCTOBER)

    assert [t["currency"] for t in body["totals"]] == ["RUB", "USD", "EUR"]
    assert {t["planned"] for t in body["totals"]} == {"0.00"}


@pytest.mark.usefixtures("october")
async def test_totals_are_counted_separately_per_currency(api: AsyncClient, token: str) -> None:
    totals = by_currency(await summary(api, token, **OCTOBER))

    assert totals["RUB"] | {"budget": None} == {
        "currency": "RUB",
        "planned": "51500.00",
        "paid": "1500.00",
        "unpaid": "50000.00",
        "overdue": "0.00",
        "paid_late": "0.00",
        "count_total": 2,
        "count_paid": 1,
        "count_overdue": 0,
        "budget": None,
        "budget_left": None,
    }
    assert (totals["USD"]["planned"], totals["USD"]["overdue"], totals["USD"]["count_overdue"]) == ("20.00", "20.00", 1)
    assert (totals["EUR"]["paid"], totals["EUR"]["paid_late"], totals["EUR"]["overdue"]) == ("9.99", "9.99", "0.00")


@pytest.mark.usefixtures("october")
async def test_totals_on_earlier_date_ignore_later_payments(api: AsyncClient, token: str) -> None:
    totals = by_currency(await summary(api, token, **OCTOBER, as_of="2026-10-11"))

    assert (totals["EUR"]["paid"], totals["EUR"]["overdue"], totals["EUR"]["count_paid"]) == ("0.00", "9.99", 0)


@pytest.mark.usefixtures("october")
async def test_default_period_is_current_month(api: AsyncClient, token: str) -> None:
    body = await summary(api, token)

    assert body["period"] == {"from": "2026-10-01", "to": "2026-10-31"}
    assert body["as_of"] == "2026-10-15"
    assert by_currency(body)["RUB"]["planned"] == "51500.00"


async def test_year_includes_planned_dues_beyond_created_periods(api: AsyncClient, token: str) -> None:
    await add_payment(api, token, name="Аренда", amount="50000", currency="RUB", next_due_date="2027-01-10")

    rub = by_currency(await summary(api, token, date_from="2027-01-01", date_to="2027-12-31"))["RUB"]

    assert (rub["planned"], rub["count_total"], rub["unpaid"]) == ("600000.00", 12, "600000.00")


async def test_stopped_payment_keeps_past_periods_but_plans_nothing(api: AsyncClient, token: str) -> None:
    payment = await add_payment(api, token, name="Сервер", amount="20", currency="USD", next_due_date="2026-09-20")
    await api.delete(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(token))

    autumn = by_currency(await summary(api, token, date_from="2026-09-01", date_to="2026-12-31"))["USD"]

    assert (autumn["planned"], autumn["count_total"]) == ("20.00", 1)


async def test_cents_are_summed_exactly(api: AsyncClient, token: str) -> None:
    for amount in ("0.10", "0.20"):
        await add_payment(
            api, token, name=f"Мелочь {amount}", amount=amount, currency="EUR", next_due_date="2026-10-20"
        )

    assert by_currency(await summary(api, token, **OCTOBER))["EUR"]["planned"] == "0.30"


@pytest.mark.usefixtures("october")
async def test_budget_applies_to_whole_month_or_year_only(
    api: AsyncClient, token: str, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Budget(
                currency=Currency.RUB, period_type=BudgetPeriodType.MONTH, year=2026, month=10, amount=Decimal(60000)
            ),
            Budget(currency=Currency.RUB, period_type=BudgetPeriodType.YEAR, year=2026, amount=Decimal(700000)),
        ]
    )
    await db_session.flush()

    month = by_currency(await summary(api, token, **OCTOBER))["RUB"]
    year = by_currency(await summary(api, token, date_from="2026-01-01", date_to="2026-12-31"))["RUB"]
    custom = by_currency(await summary(api, token, date_from="2026-10-01", date_to="2026-10-20"))["RUB"]

    assert (month["budget"], month["budget_left"]) == ("60000.00", "8500.00")
    assert year["budget"] == "700000.00"
    assert (custom["budget"], custom["budget_left"]) == (None, None)


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-31", "date_to": "2026-10-01"},
        {"date_from": "2020-01-01", "date_to": "2026-12-31"},
        {"date_from": "not-a-date"},
    ],
)
async def test_invalid_period_is_rejected(api: AsyncClient, token: str, params: dict[str, str]) -> None:
    response = await api.get("/api/v1/payments/summary", params=params, headers=bearer(token))

    assert response.status_code == 422
