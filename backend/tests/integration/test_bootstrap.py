from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import BootstrapError, sync_system_admin
from app.domain.enums import Role
from app.models import Session, User
from app.security import verify_password
from app.services.auth import open_session
from tests.conftest import USER_LOGIN


async def _system_admins(session: AsyncSession) -> list[User]:
    return list(await session.scalars(select(User).where(User.is_system)))


async def test_creates_admin_from_env(db_session: AsyncSession) -> None:
    admin = await sync_system_admin(db_session, "admin", "secret-pass-1")

    assert admin.role is Role.ADMIN
    assert admin.is_system
    assert verify_password("secret-pass-1", admin.password_hash)


async def test_repeated_start_keeps_single_admin(db_session: AsyncSession) -> None:
    first = await sync_system_admin(db_session, "admin", "secret-pass-1")
    second = await sync_system_admin(db_session, "admin", "secret-pass-1")

    assert first.id == second.id
    assert len(await _system_admins(db_session)) == 1


async def test_new_password_in_env_replaces_old_and_signs_admin_out(db_session: AsyncSession) -> None:
    admin = await sync_system_admin(db_session, "admin", "secret-pass-1")
    await open_session(db_session, admin, ttl=timedelta(hours=1), now=datetime.now(UTC), user_agent=None, ip=None)
    await db_session.flush()

    await sync_system_admin(db_session, "admin", "secret-pass-2")

    assert verify_password("secret-pass-2", admin.password_hash)
    assert await db_session.scalar(select(func.count()).select_from(Session)) == 0


async def test_changed_admin_login_retires_previous_admin(db_session: AsyncSession) -> None:
    old = await sync_system_admin(db_session, "admin", "secret-pass-1")

    new = await sync_system_admin(db_session, "boss", "secret-pass-1")

    assert [u.id for u in await _system_admins(db_session)] == [new.id]
    assert old.role is Role.USER
    assert not verify_password("secret-pass-1", old.password_hash)


async def test_admin_login_taken_by_regular_user_stops_startup(db_session: AsyncSession, regular_user: User) -> None:
    with pytest.raises(BootstrapError, match="уже занят"):
        await sync_system_admin(db_session, USER_LOGIN, "secret-pass-1")
