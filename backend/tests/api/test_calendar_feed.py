"""Подписка на календарь: личная ссылка .ics со сроками платежей для Google, Outlook и Яндекс-календаря."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login

MSK = ZoneInfo("Europe/Moscow")


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


async def create_payment(api: AsyncClient, token: str, **body: Any) -> dict[str, Any]:
    payload = {"name": "Аренда офиса", "amount": "290000", "currency": "RUB", "next_due_date": "2026-10-17", **body}
    response = await api.post("/api/v1/recurring-payments", json=payload, headers=bearer(token))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def subscribe(api: AsyncClient, token: str) -> dict[str, str]:
    response = await api.post("/api/v1/calendar/subscription", headers=bearer(token))
    assert response.status_code == 200, response.text
    urls: dict[str, str] = response.json()
    return urls


async def fetch_feed(api: AsyncClient, url: str) -> Response:
    api.cookies.clear()  # календарный сервис приходит без входа
    return await api.get(url[url.index("/api/v1/") :])


def events(body: str) -> list[str]:
    unfolded = body.replace("\r\n ", "")
    return [chunk.split("END:VEVENT")[0] for chunk in unfolded.split("BEGIN:VEVENT")[1:]]


def event_with(body: str, text: str) -> str:
    [found] = [e for e in events(body) if text in e]
    return found


# ---------- ссылка ----------


async def test_user_gets_personal_link_that_stays_the_same(
    api: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    first = await subscribe(api, user_token)
    second = await subscribe(api, user_token)

    assert first == second
    assert first["url"].endswith(".ics")
    assert "/api/v1/calendar/" in first["url"]
    assert first["webcal_url"].startswith("webcal://")
    assert first["webcal_url"].split("://")[1] == first["url"].split("://")[1]
    actions = list(await db_session.scalars(select(AuditLog.action).where(AuditLog.action.like("calendar.%"))))
    assert actions == ["calendar.link_create"]


async def test_feed_is_available_by_link_without_login(api: AsyncClient, user_token: str) -> None:
    urls = await subscribe(api, user_token)

    response = await fetch_feed(api, urls["url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")
    assert response.text.endswith("END:VCALENDAR\r\n")
    assert "X-WR-CALNAME:Invoice Keeper — платежи" in response.text


async def test_revoked_link_stops_working_and_new_one_differs(
    api: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    old = await subscribe(api, user_token)

    revoked = await api.delete("/api/v1/calendar/subscription", headers=bearer(user_token))
    new = await subscribe(api, user_token)

    assert revoked.status_code == 204
    assert (await fetch_feed(api, old["url"])).status_code == 404
    assert new["url"] != old["url"]
    assert (await fetch_feed(api, new["url"])).status_code == 200


async def test_unknown_link_is_not_found(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/calendar/not-a-real-token.ics")).status_code == 404


async def test_subscription_requires_login(api: AsyncClient) -> None:
    assert (await api.post("/api/v1/calendar/subscription")).status_code == 401


# ---------- что видно в календаре ----------


async def test_due_date_is_all_day_event_with_amount_and_reminder(
    api: AsyncClient, admin_token: str, user_token: str
) -> None:
    payment = await create_payment(api, admin_token)
    body = (await fetch_feed(api, (await subscribe(api, user_token))["url"])).text

    event = event_with(body, "DTSTART;VALUE=DATE:20261017")

    assert f"UID:{payment['id']}-0@invoice-keeper" in event
    assert "DTEND;VALUE=DATE:20261018" in event
    assert "SUMMARY:💳 Аренда офиса — 290 000\\,00 ₽" in event
    assert "Статус: к оплате" in event
    assert "TRIGGER:-P3D" in event  # напоминание за REMIND_DAYS_BEFORE дней


async def test_paid_and_overdue_periods_are_marked(api: AsyncClient, admin_token: str, user_token: str) -> None:
    payment = await create_payment(api, admin_token, next_due_date="2026-09-10", currency="USD", amount="2400")
    periods = (
        await api.get(
            "/api/v1/payment-occurrences",
            params={"recurring_payment_id": payment["id"]},
            headers=bearer(admin_token),
        )
    ).json()["items"]
    september = next(p for p in periods if p["due_date"] == "2026-09-10")
    await api.patch(
        f"/api/v1/payment-occurrences/{september['id']}",
        json={"status": "paid", "paid_date": "2026-09-09"},
        headers=bearer(user_token),
    )

    body = (await fetch_feed(api, (await subscribe(api, user_token))["url"])).text

    paid = event_with(body, "DTSTART;VALUE=DATE:20260910")
    overdue = event_with(body, "DTSTART;VALUE=DATE:20261010")
    assert "SUMMARY:✅ Оплачено: Аренда офиса" in paid
    assert "Статус: оплачено 09.09.2026 (Анна)" in paid
    assert "VALARM" not in paid  # об оплаченном не напоминаем
    assert "SUMMARY:⚠️ Просрочено: Аренда офиса" in overdue
    assert "просрочено на 5 дней" in overdue


async def test_far_future_dues_are_included_with_stable_uid(
    api: AsyncClient, admin_token: str, user_token: str
) -> None:
    payment = await create_payment(api, admin_token)
    body = (await fetch_feed(api, (await subscribe(api, user_token))["url"])).text

    june = event_with(body, "DTSTART;VALUE=DATE:20270617")  # дальше горизонта созданных периодов

    assert f"UID:{payment['id']}-8@invoice-keeper" in june  # тот же UID, когда период создадут


async def test_every_line_fits_the_standard(api: AsyncClient, admin_token: str, user_token: str) -> None:
    await create_payment(api, admin_token, name="Бухгалтерское и налоговое сопровождение; акт, ежемесячно")
    body = (await fetch_feed(api, (await subscribe(api, user_token))["url"])).text

    lines = body.split("\r\n")
    assert all(len(line.encode()) <= 75 for line in lines)
    assert "\n" not in body.replace("\r\n", "")  # только CRLF
    assert "SUMMARY:💳 Бухгалтерское и налоговое сопровождение\\; акт\\, ежемесячно" in body.replace("\r\n ", "")
