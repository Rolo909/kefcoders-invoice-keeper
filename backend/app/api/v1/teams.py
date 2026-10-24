import uuid

from fastapi import APIRouter, BackgroundTasks, Request, status

from app.api.deps import AdminUser, RemindersDep, SettingsDep, TodayDep, client_ip
from app.db import SessionDep
from app.models import Team
from app.schemas.common import LimitQuery, OffsetQuery, Page
from app.schemas.team import TeamCreate, TeamOut, TeamUpdate
from app.services import teams as teams_service

router = APIRouter(prefix="/teams", tags=["teams"])

TEAMS_PAGE_SIZE = 200

_NOT_FOUND: dict[int | str, dict[str, str]] = {status.HTTP_404_NOT_FOUND: {"description": "Команда не найдена"}}
_NAME_TAKEN: dict[int | str, dict[str, str]] = {
    status.HTTP_409_CONFLICT: {"description": "team_name_taken — команда с таким названием уже есть"}
}


def _out(team: Team, members_count: int) -> TeamOut:
    return TeamOut(
        id=team.id,
        name=team.name,
        telegram_chat_id=team.telegram_chat_id,
        members_count=members_count,
        created_at=team.created_at,
    )


@router.get("", response_model=Page[TeamOut], summary="Список команд (только администратор)")
async def list_teams(
    _: AdminUser, session: SessionDep, limit: LimitQuery = TEAMS_PAGE_SIZE, offset: OffsetQuery = 0
) -> Page[TeamOut]:
    rows, total = await teams_service.list_teams(session, limit=limit, offset=offset)
    return Page(items=[_out(team, count) for team, count in rows], total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=TeamOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создание команды (только администратор)",
    description="Общие платежи сразу появляются у новой команды — с ближайшего срока, без долгов за прошлое.",
    responses=_NAME_TAKEN,
)
async def create_team(
    body: TeamCreate,
    admin: AdminUser,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    reminders: RemindersDep,
    background: BackgroundTasks,
) -> TeamOut:
    team = await teams_service.create_team(
        session, body, actor=admin, today=today, horizon_days=settings.occurrence_horizon_days, ip=client_ip(request)
    )
    # Срок общего платежа ближе N дней — новая команда получает напоминание сразу.
    background.add_task(reminders.run)
    return _out(team, 0)


@router.patch(
    "/{team_id}",
    response_model=TeamOut,
    summary="Переименование команды или смена её Telegram-чата (только администратор)",
    responses={**_NOT_FOUND, **_NAME_TAKEN},
)
async def update_team(
    team_id: uuid.UUID, body: TeamUpdate, admin: AdminUser, request: Request, session: SessionDep
) -> TeamOut:
    team = await teams_service.update_team(session, team_id, body, actor=admin, ip=client_ip(request))
    return _out(team, await teams_service.members_count(session, team.id))


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление пустой команды (только администратор)",
    responses={
        **_NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "description": "team_not_empty — в команде есть участники, свои платежи, оплаты или чеки"
        },
    },
)
async def delete_team(team_id: uuid.UUID, admin: AdminUser, request: Request, session: SessionDep) -> None:
    await teams_service.delete_team(session, team_id, actor=admin, ip=client_ip(request))
