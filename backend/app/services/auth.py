"""Вход по логину и паролю, серверные сессии и ограничение частоты неудачных входов."""

import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, User
from app.security import hash_token, new_session_token, verify_password

# Продлеваем сессию не чаще раза в 5 минут — чтобы не писать в БД на каждый запрос.
SESSION_REFRESH_INTERVAL = timedelta(minutes=5)
USER_AGENT_MAX_LENGTH = 512


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: uuid.UUID


@dataclass(frozen=True)
class OpenedSession:
    token: str
    expires_at: datetime


class LoginRateLimiter:
    """Не больше max_failures неудачных входов на логин за окно window_seconds (в памяти процесса)."""

    def __init__(
        self, max_failures: int = 5, window_seconds: float = 60, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max_failures = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        attempts = self._failures.setdefault(key, deque())
        threshold = self._clock() - self._window
        while attempts and attempts[0] <= threshold:
            attempts.popleft()
        return attempts

    def is_blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self._max_failures

    def register_failure(self, key: str) -> None:
        self._recent(key).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


async def find_user_by_login(session: AsyncSession, login: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.login) == login.strip().lower()))


async def authenticate(session: AsyncSession, login: str, password: str) -> User | None:
    user = await find_user_by_login(session, login)
    password_ok = verify_password(password, user.password_hash if user is not None else None)
    return user if password_ok else None


async def open_session(
    session: AsyncSession, user: User, *, ttl: timedelta, now: datetime, user_agent: str | None, ip: str | None
) -> OpenedSession:
    token = new_session_token()
    expires_at = now + ttl
    session.add(
        Session(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=expires_at,
            last_seen_at=now,
            user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
            ip=ip,
        )
    )
    return OpenedSession(token=token, expires_at=expires_at)


async def resolve_session(session: AsyncSession, token: str, *, ttl: timedelta, now: datetime) -> AuthContext | None:
    """Пользователь по токену живой сессии; сессия продлевается (скользящий срок)."""
    row = (
        await session.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(token), Session.expires_at > now)
        )
    ).first()
    if row is None:
        return None
    user_session, user = row
    if now - user_session.last_seen_at >= SESSION_REFRESH_INTERVAL:
        user_session.last_seen_at = now
        user_session.expires_at = now + ttl
        await session.commit()
    return AuthContext(user=user, session_id=user_session.id)


async def close_session(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(delete(Session).where(Session.id == session_id))


async def revoke_user_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(delete(Session).where(Session.user_id == user_id))
