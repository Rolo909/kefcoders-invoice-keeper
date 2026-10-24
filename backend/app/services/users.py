"""Управление обычными пользователями. Системный админ из .env через API не меняется и не удаляется."""

import uuid

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Role
from app.errors import AppError, not_found
from app.models import User
from app.schemas.user import EMAIL_REQUIRED_FOR_NOTIFY, ProfileUpdate, UserCreate, UserUpdate
from app.security import hash_password
from app.services import audit
from app.services.audit import AuditAction
from app.services.auth import find_user_by_login, revoke_user_sessions


def _login_taken(login: str) -> AppError:
    return AppError(status.HTTP_409_CONFLICT, "login_taken", f"Логин «{login}» уже занят")


async def list_users(session: AsyncSession, *, limit: int, offset: int) -> tuple[list[User], int]:
    total = await session.scalar(select(func.count()).select_from(User)) or 0
    users = await session.scalars(
        select(User).order_by(User.is_system.desc(), User.created_at, User.login).limit(limit).offset(offset)
    )
    return list(users), total


async def _get_editable(session: AsyncSession, user_id: uuid.UUID, system_message: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("Пользователь не найден")
    if user.is_system:
        raise AppError(status.HTTP_403_FORBIDDEN, "system_user", system_message)
    return user


async def _ensure_login_free(session: AsyncSession, login: str, *, except_id: uuid.UUID | None = None) -> None:
    owner = await find_user_by_login(session, login)
    if owner is not None and owner.id != except_id:
        raise _login_taken(login)


async def _flush_unique(session: AsyncSession, login: str) -> None:
    """Защита от гонки: два одновременных запроса с одним логином упрутся в уникальный индекс."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _login_taken(login) from exc


async def create_user(session: AsyncSession, data: UserCreate, *, actor: User, ip: str | None) -> User:
    await _ensure_login_free(session, data.login)
    user = User(
        login=data.login,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        email=data.email,
        notify_email=data.notify_email,
        role=Role.USER,
        is_system=False,
    )
    session.add(user)
    await _flush_unique(session, data.login)
    audit.record(
        session,
        AuditAction.USER_CREATE,
        actor=actor,
        entity=("user", user.id),
        details={"login": user.login, "full_name": user.full_name},
        ip=ip,
    )
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession, user_id: uuid.UUID, data: UserUpdate, *, actor: User, ip: str | None
) -> User:
    user = await _get_editable(session, user_id, "Администратор задаётся в .env и не меняется через панель")
    changes = data.model_dump(exclude_unset=True)

    if data.login is not None:
        await _ensure_login_free(session, data.login, except_id=user.id)
        user.login = data.login
    if "full_name" in changes:
        user.full_name = data.full_name
    if "email" in changes:
        user.email = data.email
    if data.notify_email is not None:
        user.notify_email = data.notify_email
    if user.notify_email and user.email is None:
        raise AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", EMAIL_REQUIRED_FOR_NOTIFY)

    password_changed = data.password is not None
    if data.password is not None:
        user.password_hash = hash_password(data.password)
        await revoke_user_sessions(session, user.id)  # новый пароль — входить заново на всех устройствах

    await _flush_unique(session, user.login)
    audit.record(
        session,
        AuditAction.USER_UPDATE,
        actor=actor,
        entity=("user", user.id),
        details={"login": user.login, "password_changed": password_changed},
        ip=ip,
    )
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user_id: uuid.UUID, *, actor: User, ip: str | None) -> None:
    # Удаляет только системный админ, а его самого защищает _get_editable — удалить себя невозможно.
    user = await _get_editable(session, user_id, "Администратора из .env удалить нельзя")
    audit.record(
        session, AuditAction.USER_DELETE, actor=actor, entity=("user", user.id), details={"login": user.login}, ip=ip
    )
    await session.delete(user)
    await session.commit()


async def update_profile(session: AsyncSession, user: User, data: ProfileUpdate, *, ip: str | None) -> User:
    if user.is_system:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "system_user",
            "Учётная запись администратора задаётся в .env и не меняется через панель",
        )
    user.email = data.email
    user.notify_email = data.notify_email
    audit.record(
        session,
        AuditAction.USER_UPDATE,
        actor=user,
        entity=("user", user.id),
        details={"login": user.login, "email": user.email, "notify_email": user.notify_email},
        ip=ip,
    )
    await session.commit()
    await session.refresh(user)
    return user
