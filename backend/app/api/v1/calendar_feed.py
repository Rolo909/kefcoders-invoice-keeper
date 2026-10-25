import re
from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SettingsDep, TodayDep, client_ip, utc_now
from app.config import Settings
from app.db import SessionDep
from app.errors import not_found
from app.services import ical
from app.services.notifiers.telegram import public_panel_url
from app.services.occurrences import ensure_occurrences, views_between
from app.services.planning import planned_between

# Управление ссылкой — только после входа; сам файл .ics — по секрету в ссылке.
router = APIRouter(prefix="/calendar", tags=["calendar"])
public_router = APIRouter(prefix="/calendar", tags=["calendar"])

FEED_PATH = "/api/v1/calendar/{token}.ics"


class CalendarSubscriptionOut(BaseModel):
    url: str = Field(description="Ссылка для подписки: Google, Outlook, Яндекс-календарь («добавить по URL»)")
    webcal_url: str = Field(description="Та же ссылка в схеме webcal:// — открывает приложение календаря")


def _subscription(settings: Settings, request: Request, token: str) -> CalendarSubscriptionOut:
    base = (settings.public_web_url or str(request.base_url)).rstrip("/")
    url = base + FEED_PATH.format(token=token)
    return CalendarSubscriptionOut(url=url, webcal_url=re.sub(r"^https?://", "webcal://", url))


@router.post(
    "/subscription",
    response_model=CalendarSubscriptionOut,
    summary="Ссылка подписки на календарь сроков (.ics)",
    description="Возвращает личную ссылку; повторный вызов отдаёт ту же. Ссылку не нужно публиковать: "
    "по ней без входа видны сроки и суммы платежей.",
)
async def subscribe(
    user: CurrentUser, request: Request, session: SessionDep, settings: SettingsDep
) -> CalendarSubscriptionOut:
    token = await ical.issue_token(session, user, ip=client_ip(request))
    return _subscription(settings, request, token)


@router.delete(
    "/subscription",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отключить ссылку на календарь",
    description="Подписанные календари перестанут получать сроки. Новая ссылка — снова POST /calendar/subscription.",
)
async def unsubscribe(user: CurrentUser, request: Request, session: SessionDep) -> None:
    await ical.revoke_token(session, user, ip=client_ip(request))


@public_router.get(
    "/{token}.ics",
    response_class=Response,
    summary="Сроки платежей в формате iCalendar",
    description="Для календарных сервисов: все сроки на полгода назад и год вперёд — с суммой, статусом "
    "и напоминанием за REMIND_DAYS_BEFORE дней. Неизвестная или отключённая ссылка — 404.",
    responses={
        status.HTTP_200_OK: {"content": {"text/calendar": {}}, "description": "Файл .ics"},
        status.HTTP_404_NOT_FOUND: {"description": "Ссылка неизвестна или отключена"},
    },
)
async def feed(token: str, session: SessionDep, settings: SettingsDep, today: TodayDep) -> Response:
    if await ical.user_by_token(session, token) is None:
        raise not_found("Календарь не найден")
    await ensure_occurrences(session, today=today, horizon_days=settings.occurrence_horizon_days)
    await session.commit()
    start, end = today - timedelta(days=ical.PAST_DAYS), today + timedelta(days=ical.FUTURE_DAYS)
    panel_url = public_panel_url(settings.public_web_url)
    remind = settings.remind_days_before
    events = [
        ical.occurrence_event(v, today=today, remind_days_before=remind, panel_url=panel_url)
        for v in await views_between(session, start, end)
    ]
    events += [
        ical.planned_event(item, remind_days_before=remind, panel_url=panel_url)
        for item in await planned_between(session, start, end)
    ]
    body = ical.render_calendar(events, now=utc_now(), timezone=settings.app_timezone)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="invoice-keeper.ics"',
            "Cache-Control": "private, max-age=300",
            "X-Robots-Tag": "noindex",
        },
    )
