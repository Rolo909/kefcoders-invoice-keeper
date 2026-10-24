"""Ошибки валидации — одна строка на русском в {detail, code}; присланные данные не возвращаются."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.models import User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login


@pytest.fixture
async def admin_token(api: AsyncClient, admin: User) -> str:
    return await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)


async def detail_of(api: AsyncClient, method: str, path: str, token: str | None = None, **kwargs: Any) -> str:
    headers = {**kwargs.pop("headers", {}), **(bearer(token) if token else {})}
    response = await api.request(method, f"/api/v1{path}", headers=headers, **kwargs)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"
    detail: str = response.json()["detail"]
    return detail


async def test_password_is_never_echoed_back(api: AsyncClient) -> None:
    response = await api.post("/api/v1/auth/login", json={"login": "", "password": "my-secret-pass"})

    assert "my-secret-pass" not in response.text


async def test_missing_field_is_named_in_russian(api: AsyncClient) -> None:
    assert await detail_of(api, "POST", "/auth/login", json={"login": "anna"}) == "Не заполнено поле «Пароль»"


async def test_broken_json_is_explained(api: AsyncClient) -> None:
    detail = await detail_of(api, "POST", "/auth/login", content="{oops", headers={"content-type": "application/json"})

    assert detail == "Некорректный JSON в теле запроса"


async def test_our_own_rules_are_shown_as_is(api: AsyncClient, admin_token: str) -> None:
    detail = await detail_of(api, "POST", "/users", admin_token, json={"login": "ab", "password": "long-enough"})

    assert detail == "Логин — от 3 до 64 латинских букв, цифр, точек, дефисов или подчёркиваний"


async def test_several_errors_are_joined(api: AsyncClient, admin_token: str) -> None:
    body = {"name": "Аренда", "amount": "abc", "currency": "GBP", "next_due_date": "31.12.2026"}

    detail = await detail_of(api, "POST", "/recurring-payments", admin_token, json=body)

    assert detail == (
        "Сумма: число, например 1500.00; "
        "Валюта: допустимые значения — RUB, USD или EUR; "
        "Дата ближайшей оплаты: дата в формате ГГГГ-ММ-ДД"
    )


async def test_fixed_fields_of_period_are_refused(api: AsyncClient, admin_token: str) -> None:
    path = "/payment-occurrences/00000000-0000-0000-0000-000000000000"

    detail = await detail_of(api, "PATCH", path, admin_token, json={"due_date": "2026-12-01"})

    assert detail == "Поле «due_date» передавать нельзя"


async def test_query_parameters_are_explained(api: AsyncClient, admin_token: str) -> None:
    detail = await detail_of(api, "GET", "/payment-occurrences", admin_token, params={"limit": 0, "sort": "name"})

    assert "Размер страницы: не меньше 1" in detail
    assert "Сортировка: допустимые значения — due_date" in detail


# ---------- PATCH /auth/me ----------


async def test_user_updates_own_email_settings(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    response = await api.patch(
        "/api/v1/auth/me", json={"email": " anna@kefcoders.ru ", "notify_email": True}, headers=bearer(token)
    )

    assert response.status_code == 200
    assert (response.json()["email"], response.json()["notify_email"]) == ("anna@kefcoders.ru", True)


async def test_email_notifications_need_an_address(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    detail = await detail_of(api, "PATCH", "/auth/me", token, json={"email": "", "notify_email": True})

    assert detail == "Укажите почту, чтобы получать на неё напоминания"


async def test_role_cannot_be_changed_through_profile(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    detail = await detail_of(api, "PATCH", "/auth/me", token, json={"role": "admin"})

    assert detail == "Поле «role» передавать нельзя"


async def test_empty_required_string_reads_as_not_filled(api: AsyncClient) -> None:
    detail = await detail_of(api, "POST", "/auth/login", json={"login": "anna", "password": ""})

    assert detail == "Не заполнено поле «Пароль»"


async def test_too_long_value_mentions_limit(api: AsyncClient) -> None:
    detail = await detail_of(api, "POST", "/auth/login", json={"login": "a" * 65, "password": "x"})

    assert detail == "Логин: не длиннее 64 символов"
