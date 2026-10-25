import re
import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Session, User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login

PUBLIC_PATHS = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/docs", "/api/v1/openapi.json"}


async def _actions(db_session: AsyncSession) -> list[str]:
    return list(await db_session.scalars(select(AuditLog.action).order_by(AuditLog.at)))


async def test_every_non_public_endpoint_requires_authentication(app: FastAPI, api: AsyncClient) -> None:
    paths = {path: ops for path, ops in app.openapi()["paths"].items() if path not in PUBLIC_PATHS}
    assert paths, "в приложении должны быть защищённые маршруты"

    for path, operations in paths.items():
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for method in operations:
            response = await api.request(method.upper(), url)
            assert response.status_code == 401, f"{method.upper()} {path} доступен без входа"
            assert response.json()["code"] == "unauthorized"


async def test_login_sets_http_only_cookie_and_returns_user(api: AsyncClient, regular_user: User) -> None:
    response = await api.post("/api/v1/auth/login", json={"login": USER_LOGIN, "password": USER_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": str(regular_user.id),
        "login": USER_LOGIN,
        "full_name": "Анна",
        "email": None,
        "role": "user",
        "is_system": False,
        "telegram_linked": False,
        "notify_email": False,
        "created_at": body["user"]["created_at"],
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("ik_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


async def test_session_cookie_authenticates_following_requests(api: AsyncClient, regular_user: User) -> None:
    await login(api, USER_LOGIN, USER_PASSWORD)

    response = await api.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["login"] == USER_LOGIN


async def test_bearer_token_authenticates_api_clients(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)
    api.cookies.clear()

    response = await api.get("/api/v1/auth/me", headers=bearer(token))

    assert response.status_code == 200


async def test_login_is_case_insensitive(api: AsyncClient, regular_user: User) -> None:
    response = await api.post("/api/v1/auth/login", json={"login": " ANNA ", "password": USER_PASSWORD})

    assert response.status_code == 200


async def test_wrong_password_and_unknown_login_get_the_same_answer(api: AsyncClient, regular_user: User) -> None:
    wrong_password = await api.post("/api/v1/auth/login", json={"login": USER_LOGIN, "password": "nope-nope"})
    unknown_login = await api.post("/api/v1/auth/login", json={"login": "ghost", "password": "nope-nope"})

    for response in (wrong_password, unknown_login):
        assert response.status_code == 401
        assert response.json() == {"detail": "Неверный логин или пароль", "code": "invalid_credentials"}


async def test_me_reports_today_in_application_timezone(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    with time_machine.travel(datetime(2026, 10, 24, 22, 30, tzinfo=UTC), tick=False):
        response = await api.get("/api/v1/auth/me", headers=bearer(token))

    assert response.json()["server_today"] == "2026-10-25"
    assert response.json()["timezone"] == "Europe/Moscow"


async def test_logout_ends_only_current_session(api: AsyncClient, regular_user: User) -> None:
    other_device = await login(api, USER_LOGIN, USER_PASSWORD)
    current = await login(api, USER_LOGIN, USER_PASSWORD)

    response = await api.post("/api/v1/auth/logout", headers=bearer(current))

    assert response.status_code == 204
    assert (await api.get("/api/v1/auth/me", headers=bearer(current))).status_code == 401
    assert (await api.get("/api/v1/auth/me", headers=bearer(other_device))).status_code == 200


async def test_logout_clears_session_cookie(api: AsyncClient, regular_user: User) -> None:
    await login(api, USER_LOGIN, USER_PASSWORD)

    await api.post("/api/v1/auth/logout")

    assert (await api.get("/api/v1/auth/me")).status_code == 401


async def test_expired_session_is_rejected(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)

    with time_machine.travel(datetime.now(UTC) + timedelta(hours=169), tick=False):
        response = await api.get("/api/v1/auth/me", headers=bearer(token))

    assert response.status_code == 401


async def test_active_session_is_extended(api: AsyncClient, regular_user: User) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)
    start = datetime.now(UTC)

    with time_machine.travel(start + timedelta(hours=100), tick=False):
        assert (await api.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200
    with time_machine.travel(start + timedelta(hours=200), tick=False):
        assert (await api.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200


async def test_sixth_failed_login_within_a_minute_is_rate_limited(api: AsyncClient, regular_user: User) -> None:
    for _ in range(5):
        await api.post("/api/v1/auth/login", json={"login": USER_LOGIN, "password": "wrong-pass"})

    response = await api.post("/api/v1/auth/login", json={"login": USER_LOGIN, "password": USER_PASSWORD})

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"


async def test_logins_and_logouts_are_audited(api: AsyncClient, db_session: AsyncSession, admin: User) -> None:
    await api.post("/api/v1/auth/login", json={"login": ADMIN_LOGIN, "password": "wrong-pass"})
    token = await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)
    await api.post("/api/v1/auth/logout", headers=bearer(token))

    assert await _actions(db_session) == ["auth.login_failed", "auth.login", "auth.logout"]


# ---------- продление cookie ----------


async def test_cookie_is_renewed_together_with_session(
    api: AsyncClient, regular_user: User, db_session: AsyncSession
) -> None:
    """Сессия скользящая: при продлении на сервере браузер получает свежую cookie — иначе выкинет
    через SESSION_TTL_HOURS после входа, даже если человек заходит каждый день."""
    login_response = await api.post("/api/v1/auth/login", json={"login": USER_LOGIN, "password": USER_PASSWORD})
    assert login_response.status_code == 200
    fresh = await api.get("/api/v1/auth/me")
    assert "set-cookie" not in fresh.headers  # только что вошли — продлевать рано

    await db_session.execute(update(Session).values(last_seen_at=func.now() - timedelta(hours=1)))
    renewed = await api.get("/api/v1/auth/me")

    cookie = renewed.headers["set-cookie"]
    assert cookie.startswith(f"ik_session={api.cookies['ik_session']};")
    assert "Max-Age=604800" in cookie
    assert "HttpOnly" in cookie


async def test_bearer_requests_do_not_get_cookie(
    api: AsyncClient, regular_user: User, db_session: AsyncSession
) -> None:
    token = await login(api, USER_LOGIN, USER_PASSWORD)
    api.cookies.clear()
    await db_session.execute(update(Session).values(last_seen_at=func.now() - timedelta(hours=1)))

    response = await api.get("/api/v1/auth/me", headers=bearer(token))

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
