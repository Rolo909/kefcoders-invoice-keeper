from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.db import SessionDep
from app.domain.enums import Role
from app.errors import forbidden, unauthorized
from app.models import User
from app.services.auth import AuthContext, LoginRateLimiter, resolve_session

SESSION_COOKIE = "ik_session"

SettingsDep = Annotated[Settings, Depends(get_settings)]
_bearer = HTTPBearer(auto_error=False, description="Токен из POST /api/v1/auth/login")


def utc_now() -> datetime:
    return datetime.now(UTC)


def session_ttl(settings: Settings) -> timedelta:
    return timedelta(hours=settings.session_ttl_hours)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_login_limiter(request: Request) -> LoginRateLimiter:
    limiter: LoginRateLimiter = request.app.state.login_limiter
    return limiter


async def get_auth(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    """Сессия из заголовка Authorization: Bearer (Swagger, API-клиенты) или из cookie (веб-панель)."""
    token = credentials.credentials if credentials is not None else request.cookies.get(SESSION_COOKIE)
    if not token:
        raise unauthorized()
    auth = await resolve_session(session, token, ttl=session_ttl(settings), now=utc_now())
    if auth is None:
        raise unauthorized()
    return auth


CurrentAuth = Annotated[AuthContext, Depends(get_auth)]


async def get_current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role is not Role.ADMIN:
        raise forbidden()
    return user


AdminUser = Annotated[User, Depends(require_admin)]
LoginLimiterDep = Annotated[LoginRateLimiter, Depends(get_login_limiter)]
