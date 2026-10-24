import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import AdminUser, RemindersDep, SettingsDep
from app.api.v1.presenters import audit_log_out, notification_out
from app.db import SessionDep
from app.domain.enums import NotificationChannel, NotificationStatus
from app.schemas.common import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery, Page
from app.schemas.payment import AuditLogOut, NotificationLogOut
from app.services import logs as logs_service
from app.services import teams as teams_service
from app.services.logs import AuditFilter
from app.services.notifiers.base import TeamTarget

router = APIRouter(tags=["logs"])


@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="Журнал входов и действий (администратор)")
async def audit_logs(
    _: AdminUser,
    session: SessionDep,
    settings: SettingsDep,
    action: Annotated[str | None, Query(max_length=64, description="Например auth — все входы и выходы")] = None,
    actor_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
) -> Page[AuditLogOut]:
    filters = AuditFilter(action=action, actor_id=actor_id, date_from=date_from, date_to=date_to)
    rows, total = await logs_service.list_audit_logs(session, filters, tz=settings.timezone, limit=limit, offset=offset)
    return Page(items=[audit_log_out(log, actor) for log, actor in rows], total=total, limit=limit, offset=offset)


@router.get(
    "/notifications", response_model=Page[NotificationLogOut], summary="Журнал напоминаний по каналам (администратор)"
)
async def notifications(
    _: AdminUser,
    session: SessionDep,
    channel: NotificationChannel | None = None,
    status: NotificationStatus | None = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
) -> Page[NotificationLogOut]:
    rows, total = await logs_service.list_notifications(
        session, channel=channel, status=status, limit=limit, offset=offset
    )
    items = [notification_out(n, payment_name=p.name, due_date=o.due_date, team=t) for n, o, p, t in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


class ChannelCheckOut(BaseModel):
    channel: NotificationChannel
    ok: bool
    error: str | None


class NotificationTestOut(BaseModel):
    channels: list[ChannelCheckOut]


@router.post(
    "/notifications/test",
    response_model=NotificationTestOut,
    summary="Тестовое сообщение во все каналы — проверка настроек (администратор)",
)
async def test_notifications(
    _: AdminUser,
    reminders: RemindersDep,
    session: SessionDep,
    team_id: Annotated[
        uuid.UUID | None, Query(description="Проверить чат и почту этой команды; без него — общий чат из .env")
    ] = None,
) -> NotificationTestOut:
    team = None if team_id is None else await teams_service.get_team(session, team_id)
    target = None if team is None else TeamTarget(id=team.id, name=team.name, telegram_chat_id=team.telegram_chat_id)
    results = await reminders.check_channels(target)
    return NotificationTestOut(
        channels=[ChannelCheckOut(channel=channel, ok=r.ok, error=r.error) for channel, r in results]
    )
