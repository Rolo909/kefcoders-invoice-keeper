import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Team, User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login

NEW_USER = {"login": "maria", "password": "maria-password", "full_name": "Мария", "email": "maria@kefcoders.ru"}


@pytest.fixture
def new_user(team: Team) -> dict[str, object]:
    return {**NEW_USER, "team_id": str(team.id)}


@pytest.fixture
async def admin_token(api: AsyncClient, admin: User) -> str:
    return await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)


@pytest.fixture
async def user_token(api: AsyncClient, regular_user: User) -> str:
    return await login(api, USER_LOGIN, USER_PASSWORD)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("PATCH", "/api/v1/users/{id}"),
        ("DELETE", "/api/v1/users/{id}"),
    ],
)
async def test_regular_user_cannot_manage_users_via_api(
    api: AsyncClient, user_token: str, regular_user: User, method: str, path: str, new_user: dict[str, object]
) -> None:
    response = await api.request(
        method, path.format(id=regular_user.id), headers=bearer(user_token), json=new_user if method == "POST" else {}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_creates_regular_user_who_can_log_in(
    api: AsyncClient, admin_token: str, new_user: dict[str, object]
) -> None:
    response = await api.post("/api/v1/users", json=new_user, headers=bearer(admin_token))

    assert response.status_code == 201
    created = response.json()
    assert created["role"] == "user"
    assert created["is_system"] is False
    assert created["full_name"] == "Мария"
    await login(api, "maria", "maria-password")


async def test_role_cannot_be_set_when_creating_user(
    api: AsyncClient, admin_token: str, new_user: dict[str, object]
) -> None:
    response = await api.post("/api/v1/users", json={**new_user, "role": "admin"}, headers=bearer(admin_token))

    assert response.status_code == 422


async def test_login_must_be_unique_regardless_of_case(
    api: AsyncClient, admin_token: str, regular_user: User, new_user: dict[str, object]
) -> None:
    response = await api.post("/api/v1/users", json={**new_user, "login": "ANNA"}, headers=bearer(admin_token))

    assert response.status_code == 409
    assert response.json() == {"detail": "Логин «ANNA» уже занят", "code": "login_taken"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"login": "мария"},
        {"login": "ab"},
        {"password": "short"},
        {"email": "not-an-email"},
        {"email": None, "notify_email": True},
    ],
)
async def test_invalid_user_data_is_rejected(
    api: AsyncClient, admin_token: str, overrides: dict[str, object], new_user: dict[str, object]
) -> None:
    response = await api.post("/api/v1/users", json={**new_user, **overrides}, headers=bearer(admin_token))

    assert response.status_code == 422


async def test_list_returns_system_admin_first(api: AsyncClient, admin_token: str, regular_user: User) -> None:
    response = await api.get("/api/v1/users", headers=bearer(admin_token))

    body = response.json()
    assert body["total"] == 2
    assert [u["login"] for u in body["items"]] == [ADMIN_LOGIN, USER_LOGIN]
    assert body["limit"] == 50


async def test_admin_updates_user_fields(api: AsyncClient, admin_token: str, regular_user: User) -> None:
    response = await api.patch(
        f"/api/v1/users/{regular_user.id}",
        json={"full_name": "Анна Петрова", "email": "anna@kefcoders.ru", "notify_email": True},
        headers=bearer(admin_token),
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Анна Петрова"
    assert response.json()["notify_email"] is True


async def test_empty_password_in_update_means_no_change(api: AsyncClient, admin_token: str, regular_user: User) -> None:
    await api.patch(f"/api/v1/users/{regular_user.id}", json={"password": ""}, headers=bearer(admin_token))

    await login(api, USER_LOGIN, USER_PASSWORD)


async def test_password_change_signs_user_out_everywhere(
    api: AsyncClient, admin_token: str, user_token: str, regular_user: User
) -> None:
    response = await api.patch(
        f"/api/v1/users/{regular_user.id}", json={"password": "brand-new-pass"}, headers=bearer(admin_token)
    )

    assert response.status_code == 200
    assert (await api.get("/api/v1/auth/me", headers=bearer(user_token))).status_code == 401
    await login(api, USER_LOGIN, "brand-new-pass")


async def test_renaming_to_taken_login_is_rejected(api: AsyncClient, admin_token: str, regular_user: User) -> None:
    response = await api.patch(f"/api/v1/users/{regular_user.id}", json={"login": "Admin"}, headers=bearer(admin_token))

    assert response.status_code == 409


async def test_system_admin_cannot_be_changed_or_deleted(api: AsyncClient, admin_token: str, admin: User) -> None:
    patched = await api.patch(f"/api/v1/users/{admin.id}", json={"full_name": "x"}, headers=bearer(admin_token))
    deleted = await api.delete(f"/api/v1/users/{admin.id}", headers=bearer(admin_token))

    for response in (patched, deleted):
        assert response.status_code == 403
        assert response.json()["code"] == "system_user"


async def test_deleted_user_loses_access(
    api: AsyncClient, admin_token: str, user_token: str, regular_user: User, db_session: AsyncSession
) -> None:
    response = await api.delete(f"/api/v1/users/{regular_user.id}", headers=bearer(admin_token))

    assert response.status_code == 204
    assert (await api.get("/api/v1/auth/me", headers=bearer(user_token))).status_code == 401
    audit_login = await db_session.scalar(select(AuditLog.details).where(AuditLog.action == "user.delete"))
    assert audit_login == {"login": USER_LOGIN}


async def test_unknown_user_is_not_found(api: AsyncClient, admin_token: str) -> None:
    response = await api.delete(f"/api/v1/users/{uuid.uuid4()}", headers=bearer(admin_token))

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# ---------- команда пользователя ----------


@pytest.mark.parametrize("team_id", [None, "missing", str(uuid.UUID(int=1))])
async def test_user_is_created_only_in_existing_team(
    api: AsyncClient, admin_token: str, new_user: dict[str, object], team_id: str | None
) -> None:
    body = {key: value for key, value in new_user.items() if key != "team_id"}
    if team_id != "missing":
        body["team_id"] = team_id

    response = await api.post("/api/v1/users", json=body, headers=bearer(admin_token))

    assert response.status_code == 422


async def test_moving_user_to_another_team_is_audited(
    api: AsyncClient, admin_token: str, regular_user: User, team: Team, db_session: AsyncSession
) -> None:
    studio = Team(name="Студия дизайна")
    db_session.add(studio)
    await db_session.flush()

    response = await api.patch(
        f"/api/v1/users/{regular_user.id}", json={"team_id": str(studio.id)}, headers=bearer(admin_token)
    )

    assert response.status_code == 200
    assert regular_user.team_id == studio.id
    details = await db_session.scalar(select(AuditLog.details).where(AuditLog.action == "user.update"))
    assert details is not None
    assert (details["old_team"], details["new_team"]) == (team.name, "Студия дизайна")
