from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.db import SessionDep
from app.domain.enums import Role
from app.domain.status import today_in
from app.errors import forbidden, unauthorized
from app.models import User
from app.services.auth import AuthContext, LoginRateLimiter, resolve_session
from app.services.reminders import ReminderDispatcher

SESSION_COOKIE = "ik_session"

SettingsDep = Annotated[Settings, Depends(get_settings)]
_bearer = HTTPBearer(auto_error=False, description="Токен из POST /api/v1/auth/login")


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_today(settings: SettingsDep) -> date:
    """«Сегодня» в едином часовом поясе приложения (APP_TIMEZONE)."""
    return today_in(settings.timezone)


TodayDep = Annotated[date, Depends(get_today)]


def session_ttl(settings: Settings) -> timedelta:
    return timedelta(hours=settings.session_ttl_hours)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_reminders(request: Request) -> ReminderDispatcher:
    dispatcher: ReminderDispatcher = request.app.state.reminders
    return dispatcher


RemindersDep = Annotated[ReminderDispatcher, Depends(get_reminders)]


def get_login_limiter(request: Request) -> LoginRateLimiter:
    limiter: LoginRateLimiter = request.app.state.login_limiter
    return limiter


def set_session_cookie(response: Response, request: Request, token: str, settings: Settings) -> None:
    """Cookie сессии веб-панели: живёт столько же, сколько сессия на сервере."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(session_ttl(settings).total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


async def get_auth(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    """Сессия из заголовка Authorization: Bearer (Swagger, API-клиенты) или из cookie (веб-панель)."""
    cookie = request.cookies.get(SESSION_COOKIE)
    token = credentials.credentials if credentials is not None else cookie
    if not token:
        raise unauthorized()
    auth = await resolve_session(session, token, ttl=session_ttl(settings), now=utc_now())
    if auth is None:
        raise unauthorized()
    if auth.refreshed and token == cookie:
        # Сессия скользящая: продлили на сервере — продлеваем и cookie, иначе браузер забудет её
        # через SESSION_TTL_HOURS после входа, даже если человек заходит каждый день.
        set_session_cookie(response, request, token, settings)
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
