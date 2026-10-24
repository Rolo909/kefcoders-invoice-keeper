from fastapi import APIRouter, Request, Response, status

from app.api.deps import (
    SESSION_COOKIE,
    CurrentAuth,
    CurrentUser,
    LoginLimiterDep,
    SettingsDep,
    client_ip,
    session_ttl,
    utc_now,
)
from app.db import SessionDep
from app.domain.status import today_in
from app.errors import AppError
from app.schemas.auth import LoginIn, LoginOut
from app.schemas.user import MeOut, UserOut
from app.services import audit
from app.services.audit import AuditAction
from app.services.auth import authenticate, close_session, open_session

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"])

_ERROR_RESPONSES: dict[int | str, dict[str, str]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Неверный логин или пароль"},
    status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много неудачных попыток входа"},
}


@public_router.post("/login", response_model=LoginOut, summary="Вход по логину и паролю", responses=_ERROR_RESPONSES)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LoginLimiterDep,
) -> LoginOut:
    limiter_key = body.login.strip().lower()
    if limiter.is_blocked(limiter_key):
        raise AppError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Слишком много попыток входа. Попробуйте снова через минуту.",
        )

    ip = client_ip(request)
    user = await authenticate(session, body.login, body.password)
    if user is None:
        limiter.register_failure(limiter_key)
        audit.record(
            session, AuditAction.LOGIN_FAILED, actor=None, actor_login=body.login, details={"login": body.login}, ip=ip
        )
        await session.commit()
        raise AppError(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Неверный логин или пароль")

    limiter.reset(limiter_key)
    opened = await open_session(
        session, user, ttl=session_ttl(settings), now=utc_now(), user_agent=request.headers.get("user-agent"), ip=ip
    )
    audit.record(session, AuditAction.LOGIN, actor=user, entity=("user", user.id), ip=ip)
    await session.commit()

    response.set_cookie(
        SESSION_COOKIE,
        opened.token,
        max_age=int(session_ttl(settings).total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return LoginOut(access_token=opened.token, expires_at=opened.expires_at, user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut, summary="Текущий пользователь")
async def me(user: CurrentUser, settings: SettingsDep) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(user),
        server_today=today_in(settings.timezone),
        timezone=settings.app_timezone,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Завершение текущей сессии")
async def logout(auth: CurrentAuth, request: Request, response: Response, session: SessionDep) -> None:
    await close_session(session, auth.session_id)
    audit.record(session, AuditAction.LOGOUT, actor=auth.user, entity=("user", auth.user.id), ip=client_ip(request))
    await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
