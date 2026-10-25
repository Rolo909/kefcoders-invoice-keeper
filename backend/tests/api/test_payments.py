"""Регулярные платежи и периоды: ARCHITECTURE.md §4.2–4.6, критерии приёмки «Регулярность», «Статусы и просрочка»."""

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from httpx import AsyncClient, Response

from app.models import User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, RecordingNotifier, bearer, login

TODAY = date(2026, 10, 15)
MSK = ZoneInfo("Europe/Moscow")
RENT = {"name": "Аренда офиса", "amount": "50000.00", "currency": "RUB", "period": "monthly"}


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, 0, tzinfo=MSK), tick=False):
        yield


@pytest.fixture
async def admin_token(api: AsyncClient, admin: User) -> str:
    return await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)


@pytest.fixture
async def user_token(api: AsyncClient, regular_user: User) -> str:
    return await login(api, USER_LOGIN, USER_PASSWORD)


async def create_payment(api: AsyncClient, token: str, **overrides: Any) -> dict[str, Any]:
    body = {**RENT, "next_due_date": (TODAY + timedelta(days=10)).isoformat(), **overrides}
    response = await api.post("/api/v1/recurring-payments", json=body, headers=bearer(token))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def periods(api: AsyncClient, token: str, **params: Any) -> list[dict[str, Any]]:
    response = await api.get("/api/v1/payment-occurrences", params={"limit": 500, **params}, headers=bearer(token))
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def patch_period(api: AsyncClient, token: str, period_id: str, **body: Any) -> Response:
    return await api.patch(f"/api/v1/payment-occurrences/{period_id}", json=body, headers=bearer(token))


# ---------- создание и расписание ----------


async def test_admin_creates_payment_with_its_first_period(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)

    assert payment["amount"] == "50000.00"
    assert payment["first_due_date"] == "2026-10-25"
    assert payment["created_by"]["login"] == ADMIN_LOGIN
    nxt = payment["next_occurrence"]
    assert (nxt["due_date"], nxt["status"], nxt["state"]) == ("2026-10-25", "unpaid", "upcoming")


async def test_periods_cover_horizon_and_each_has_its_own_status(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token)

    items = await periods(api, admin_token)

    # горизонт: 15.10 + 60 дней = 14.12
    assert [p["due_date"] for p in items] == ["2026-10-25", "2026-11-25"]
    assert [p["seq"] for p in items] == [0, 1]
    assert len({p["id"] for p in items}) == 2


async def test_past_start_date_creates_overdue_periods_and_a_future_one(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, next_due_date="2026-08-31")

    items = await periods(api, admin_token)

    assert [(p["due_date"], p["state"]) for p in items[:4]] == [
        ("2026-08-31", "overdue"),
        ("2026-09-30", "overdue"),
        ("2026-10-31", "upcoming"),
        ("2026-11-30", "upcoming"),
    ]


async def test_end_date_stops_the_schedule(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, end_date="2026-11-30")

    assert [p["due_date"] for p in await periods(api, admin_token)] == ["2026-10-25", "2026-11-25"]


async def test_new_periods_appear_as_time_goes_by(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token)

    with time_machine.travel(datetime(2027, 1, 20, 12, 0, tzinfo=MSK), tick=False):
        token = await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)
        items = await periods(api, token)

    assert items[-1]["due_date"] == "2027-02-25"  # 20.01 + 60 дней = 21.03
    assert [p["seq"] for p in items] == list(range(len(items)))


async def test_amount_snapshot_and_currency_are_kept_per_period(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, amount="20", currency="USD", name="Сервер")

    items = await periods(api, admin_token)

    assert {(p["amount"], p["currency"]) for p in items} == {("20.00", "USD")}


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "0"},
        {"amount": "-5"},
        {"amount": "10.999"},
        {"currency": "GBP"},
        {"name": "   "},
        {"end_date": "2026-10-01"},
        {"next_due_date": "2025-01-01"},
        {"due_date": "2026-10-25"},
    ],
)
async def test_invalid_payment_is_rejected(api: AsyncClient, admin_token: str, overrides: dict[str, Any]) -> None:
    body = {**RENT, "next_due_date": "2026-10-25", **overrides}

    response = await api.post("/api/v1/recurring-payments", json=body, headers=bearer(admin_token))

    assert response.status_code == 422


# ---------- права ----------


async def test_user_cannot_create_or_stop_payments(api: AsyncClient, admin_token: str, user_token: str) -> None:
    payment = await create_payment(api, admin_token)

    created = await api.post(
        "/api/v1/recurring-payments", json={**RENT, "next_due_date": "2026-10-25"}, headers=bearer(user_token)
    )
    stopped = await api.delete(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(user_token))

    assert (created.status_code, stopped.status_code) == (403, 403)


async def test_user_sees_payments_and_marks_payment(api: AsyncClient, admin_token: str, user_token: str) -> None:
    payment = await create_payment(api, admin_token)

    listed = await api.get("/api/v1/recurring-payments", headers=bearer(user_token))
    paid = await patch_period(api, user_token, payment["next_occurrence"]["id"], status="paid")

    assert listed.json()["total"] == 1
    assert paid.status_code == 200
    assert paid.json()["paid_by"]["login"] == USER_LOGIN


# ---------- оплата, отмена, исправление даты ----------


async def test_marking_one_period_paid_leaves_others_unpaid(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token)
    first, *rest = await periods(api, admin_token)

    response = await patch_period(api, admin_token, first["id"], status="paid")

    assert response.json()["paid_date"] == "2026-10-15"
    assert response.json()["state"] == "paid"
    assert {p["status"] for p in (await periods(api, admin_token))[1:]} == {"unpaid"}
    assert len(rest) == 1


async def test_cancelling_payment_clears_actual_date(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)
    period_id = payment["next_occurrence"]["id"]
    await patch_period(api, admin_token, period_id, status="paid", paid_date="2026-10-14")

    response = await patch_period(api, admin_token, period_id, status="unpaid")

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["paid_date"], response.json()["paid_by"]) == (
        "unpaid",
        None,
        None,
    )


async def test_correcting_paid_date_removes_wrong_overdue(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, next_due_date="2026-10-01")
    period = (await periods(api, admin_token))[0]
    late = await patch_period(api, admin_token, period["id"], status="paid", paid_date="2026-10-10")

    corrected = await patch_period(api, admin_token, period["id"], paid_date="2026-10-01")

    assert (late.json()["state"], late.json()["is_overdue"], late.json()["days_overdue"]) == ("paid_late", True, 9)
    assert (corrected.json()["state"], corrected.json()["is_overdue"]) == ("paid", False)
    assert corrected.json()["due_date"] == "2026-10-01"


async def test_payment_on_due_date_is_on_time(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, next_due_date="2026-10-15")
    period = (await periods(api, admin_token))[0]

    response = await patch_period(api, admin_token, period["id"], status="paid")

    assert response.json()["is_overdue"] is False


async def test_future_paid_date_is_rejected(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)

    response = await patch_period(
        api, admin_token, payment["next_occurrence"]["id"], status="paid", paid_date="2026-10-16"
    )

    assert response.status_code == 422


async def test_changing_date_of_unpaid_period_is_a_conflict(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)

    response = await patch_period(api, admin_token, payment["next_occurrence"]["id"], paid_date="2026-10-10")

    assert response.status_code == 409
    assert response.json()["code"] == "not_paid"


@pytest.mark.parametrize("body", [{}, {"due_date": "2026-12-01"}, {"amount": "1.00"}])
async def test_due_date_and_amount_cannot_be_changed(api: AsyncClient, admin_token: str, body: dict[str, Any]) -> None:
    payment = await create_payment(api, admin_token)

    response = await patch_period(api, admin_token, payment["next_occurrence"]["id"], **body)

    assert response.status_code == 422


async def test_unknown_period_is_not_found(api: AsyncClient, admin_token: str) -> None:
    response = await patch_period(api, admin_token, str(uuid.uuid4()), status="paid")

    assert response.status_code == 404


async def test_period_detail_contains_payment_history(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token, next_due_date="2026-10-01")
    period_id = (await periods(api, admin_token))[0]["id"]
    await patch_period(api, admin_token, period_id, status="paid", paid_date="2026-10-03")
    await patch_period(api, admin_token, period_id, paid_date="2026-10-01")
    await patch_period(api, admin_token, period_id, status="unpaid")

    detail = (await api.get(f"/api/v1/payment-occurrences/{period_id}", headers=bearer(admin_token))).json()

    assert [h["action"] for h in detail["history"]] == [
        "occurrence.mark_paid",
        "occurrence.change_paid_date",
        "occurrence.mark_unpaid",
    ]
    assert detail["history"][1]["details"] == {
        "payment_name": payment["name"],
        "due_date": "2026-10-01",
        "old_paid_date": "2026-10-03",
        "new_paid_date": "2026-10-01",
    }
    assert detail["reminders"] == []


# ---------- ближайший период ----------


async def test_next_occurrence_is_earliest_unpaid_even_if_overdue(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token, next_due_date="2026-09-10")

    detail = (await api.get(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(admin_token))).json()

    assert detail["next_occurrence"]["due_date"] == "2026-09-10"
    assert [o["due_date"] for o in detail["occurrences"]][-1] == "2026-09-10"


async def test_next_occurrence_moves_on_after_payment(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)
    await patch_period(api, admin_token, payment["next_occurrence"]["id"], status="paid")

    detail = (await api.get(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(admin_token))).json()

    assert detail["next_occurrence"]["due_date"] == "2026-11-25"


# ---------- прекращение ----------


async def test_stopping_keeps_history_and_removes_future_unpaid_periods(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token, next_due_date="2026-09-15")
    items = await periods(api, admin_token)
    await patch_period(api, admin_token, items[0]["id"], status="paid", paid_date="2026-09-15")

    response = await api.delete(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(admin_token))

    assert response.status_code == 204
    kept = await periods(api, admin_token)
    assert [(p["due_date"], p["status"]) for p in kept] == [("2026-09-15", "paid"), ("2026-10-15", "unpaid")]
    assert {p["recurring_payment"]["is_deleted"] for p in kept} == {True}


async def test_stopped_payment_gets_no_new_periods(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)
    await api.delete(f"/api/v1/recurring-payments/{payment['id']}", headers=bearer(admin_token))

    with time_machine.travel(datetime(2027, 6, 1, 12, 0, tzinfo=MSK), tick=False):
        token = await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)
        assert await periods(api, token) == []


async def test_stopped_payment_is_hidden_unless_requested(api: AsyncClient, admin_token: str) -> None:
    active = await create_payment(api, admin_token, name="Сервер")
    stopped = await create_payment(api, admin_token, name="Старая подписка")
    await api.delete(f"/api/v1/recurring-payments/{stopped['id']}", headers=bearer(admin_token))

    default = (await api.get("/api/v1/recurring-payments", headers=bearer(admin_token))).json()
    everything = (
        await api.get("/api/v1/recurring-payments", params={"include_deleted": True}, headers=bearer(admin_token))
    ).json()

    assert [p["id"] for p in default["items"]] == [active["id"]]
    assert [p["id"] for p in everything["items"]] == [active["id"], stopped["id"]]
    assert everything["items"][1]["is_active"] is False


async def test_stopping_twice_is_harmless(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)
    url = f"/api/v1/recurring-payments/{payment['id']}"

    first = await api.delete(url, headers=bearer(admin_token))
    second = await api.delete(url, headers=bearer(admin_token))

    assert (first.status_code, second.status_code) == (204, 204)


# ---------- фильтры и сортировка ----------


async def test_overdue_filter_matches_computed_flag(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, next_due_date="2026-08-15", name="Сервер", currency="USD", amount="20")
    items = await periods(api, admin_token)
    await patch_period(api, admin_token, items[0]["id"], status="paid", paid_date="2026-08-15")  # вовремя
    await patch_period(api, admin_token, items[1]["id"], status="paid", paid_date="2026-09-20")  # с опозданием
    everything = await periods(api, admin_token)

    overdue = await periods(api, admin_token, overdue=True)
    not_overdue = await periods(api, admin_token, overdue=False)

    assert {p["id"] for p in overdue} == {p["id"] for p in everything if p["is_overdue"]}
    assert {p["id"] for p in not_overdue} == {p["id"] for p in everything if not p["is_overdue"]}
    assert [p["due_date"] for p in overdue] == ["2026-09-15"]


@pytest.mark.parametrize("state", ["paid", "paid_late", "overdue", "due_soon", "upcoming"])
async def test_state_filter_matches_computed_state(api: AsyncClient, admin_token: str, state: str) -> None:
    await create_payment(api, admin_token, next_due_date="2026-07-17", period="weekly", amount="10")
    items = await periods(api, admin_token)
    await patch_period(api, admin_token, items[0]["id"], status="paid", paid_date="2026-07-17")
    await patch_period(api, admin_token, items[1]["id"], status="paid", paid_date="2026-07-30")
    everything = await periods(api, admin_token)

    filtered = await periods(api, admin_token, state=state)

    assert filtered
    assert {p["id"] for p in filtered} == {p["id"] for p in everything if p["state"] == state}


async def test_filters_by_several_currencies_and_sorts_by_overdue_days(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, name="Аренда", next_due_date="2026-10-05")
    await create_payment(api, admin_token, name="Сервер", currency="USD", amount="20", next_due_date="2026-09-25")
    await create_payment(api, admin_token, name="Подписка", currency="EUR", amount="9.99", next_due_date="2026-10-10")

    items = await periods(api, admin_token, currency=["USD", "EUR"], overdue=True, sort="-days_overdue")

    assert [(p["recurring_payment"]["name"], p["days_overdue"]) for p in items] == [
        ("Сервер", 20),
        ("Подписка", 5),
    ]


async def test_list_is_paginated(api: AsyncClient, admin_token: str) -> None:
    await create_payment(api, admin_token, period="weekly")

    response = await api.get(
        "/api/v1/payment-occurrences", params={"limit": 2, "offset": 1}, headers=bearer(admin_token)
    )

    body = response.json()
    assert (len(body["items"]), body["limit"], body["offset"]) == (2, 2, 1)
    assert body["total"] > 3


# ---------- напоминание сразу при создании ----------


async def test_payment_added_less_than_three_days_before_due_is_reminded_at_once(
    api: AsyncClient, admin_token: str, notifier: RecordingNotifier
) -> None:
    payment = await create_payment(api, admin_token, next_due_date="2026-10-16")

    assert [(r.payment_name, r.due_date.isoformat()) for r in notifier.sent] == [("Аренда офиса", "2026-10-16")]
    detail = (
        await api.get(f"/api/v1/payment-occurrences/{payment['next_occurrence']['id']}", headers=bearer(admin_token))
    ).json()
    assert [(r["channel"], r["kind"], r["status"]) for r in detail["reminders"]] == [("telegram", "before_due", "sent")]
    assert detail["last_reminder_at"] is not None


async def test_payment_far_from_due_date_is_not_reminded_yet(
    api: AsyncClient, admin_token: str, notifier: RecordingNotifier
) -> None:
    await create_payment(api, admin_token, next_due_date="2026-10-25")

    assert notifier.sent == []


# ---------- повторная отметка оплаты ----------


async def test_second_user_cannot_mark_already_paid_period(api: AsyncClient, admin_token: str, user_token: str) -> None:
    payment = await create_payment(api, admin_token)
    period_id = payment["next_occurrence"]["id"]
    await patch_period(api, user_token, period_id, status="paid", paid_date="2026-10-14")

    second = await patch_period(api, admin_token, period_id, status="paid", paid_date="2026-10-15")

    assert second.status_code == 409
    assert second.json() == {"detail": "Уже оплачено: Анна, 14.10.2026. Обновите страницу.", "code": "already_paid"}
    period = (await api.get(f"/api/v1/payment-occurrences/{period_id}", headers=bearer(admin_token))).json()
    assert (period["paid_date"], period["paid_by"]["login"]) == ("2026-10-14", USER_LOGIN)
    assert [h["action"] for h in period["history"]] == ["occurrence.mark_paid"]


async def test_paid_date_is_changed_by_sending_only_the_date(api: AsyncClient, admin_token: str) -> None:
    payment = await create_payment(api, admin_token)
    period_id = payment["next_occurrence"]["id"]
    await patch_period(api, admin_token, period_id, status="paid", paid_date="2026-10-14")

    changed = await patch_period(api, admin_token, period_id, paid_date="2026-10-12")

    assert changed.status_code == 200
    assert changed.json()["paid_date"] == "2026-10-12"
