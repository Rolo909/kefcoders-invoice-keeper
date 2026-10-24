"""Синхронизация администратора из .env — единственный способ задать администратора.

Запускается при старте контейнера: `python -m app.bootstrap`.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import engine, session_factory
from app.domain.enums import Role
from app.logging_setup import configure_logging
from app.models import User
from app.security import LOCKED_PASSWORD_HASH, hash_password, verify_password
from app.services.auth import find_user_by_login, revoke_user_sessions

logger = logging.getLogger(__name__)


class BootstrapError(RuntimeError):
    pass


async def _retire(session: AsyncSession, former: User) -> None:
    """Прежний системный админ (сменили ADMIN_LOGIN): вход закрыт, сессии отозваны, история сохранена."""
    former.is_system = False
    former.role = Role.USER
    former.password_hash = LOCKED_PASSWORD_HASH
    await revoke_user_sessions(session, former.id)
    await session.flush()
    logger.warning("Администратор %s больше не задан в .env — вход для него закрыт", former.login)


async def sync_system_admin(session: AsyncSession, login: str, password: str) -> User:
    current = await session.scalar(select(User).where(User.is_system))
    if current is not None and current.login.lower() != login.strip().lower():
        await _retire(session, current)
        current = None

    if current is None:
        existing = await find_user_by_login(session, login)
        if existing is not None:
            raise BootstrapError(
                f"Логин «{login}» из ADMIN_LOGIN уже занят обычным пользователем — выберите другой ADMIN_LOGIN"
            )
        current = User(login=login.strip(), password_hash=hash_password(password), role=Role.ADMIN, is_system=True)
        session.add(current)
        logger.info("Создан администратор %s", current.login)
    elif not verify_password(password, current.password_hash):
        current.password_hash = hash_password(password)
        await revoke_user_sessions(session, current.id)
        logger.info("Пароль администратора %s обновлён из .env", current.login)

    current.role = Role.ADMIN
    await session.flush()
    return current


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        async with session_factory() as session:
            await sync_system_admin(session, settings.admin_login, settings.admin_password.get_secret_value())
            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
