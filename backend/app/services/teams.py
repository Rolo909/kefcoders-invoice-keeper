"""Команды: создание, переименование, чат напоминаний, удаление пустой команды."""

import uuid
from datetime import date

from fastapi import status
from sqlalchemy import ScalarSelect, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OccurrenceStatus
from app.errors import AppError, not_found
from app.models import Attachment, PaymentOccurrence, RecurringPayment, Team, User
from app.schemas.team import TeamCreate, TeamUpdate
from app.services import audit
from app.services.audit import AuditAction
from app.services.occurrences import ensure_occurrences

NOT_EMPTY = "В команде есть участники, свои платежи или оплаты — удалить её нельзя"


def _name_taken(name: str) -> AppError:
    return AppError(status.HTTP_409_CONFLICT, "team_name_taken", f"Команда «{name}» уже есть")


def _members_count() -> ScalarSelect[int]:
    return select(func.count(User.id)).where(User.team_id == Team.id).correlate(Team).scalar_subquery()


async def members_count(session: AsyncSession, team_id: uuid.UUID) -> int:
    return await session.scalar(select(func.count(User.id)).where(User.team_id == team_id)) or 0


async def list_teams(session: AsyncSession, *, limit: int, offset: int) -> tuple[list[tuple[Team, int]], int]:
    """Команды по названию с числом участников."""
    total = await session.scalar(select(func.count()).select_from(Team)) or 0
    rows = await session.execute(
        select(Team, _members_count()).order_by(func.lower(Team.name), Team.id).limit(limit).offset(offset)
    )
    return [(team, count or 0) for team, count in rows], total


async def _ensure_name_free(session: AsyncSession, name: str, *, except_id: uuid.UUID | None = None) -> None:
    owner = await session.scalar(select(Team.id).where(func.lower(Team.name) == name.lower()))
    if owner is not None and owner != except_id:
        raise _name_taken(name)


async def _flush_unique(session: AsyncSession, name: str) -> None:
    """Два одновременных запроса с одним названием упрутся в уникальный индекс."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _name_taken(name) from exc


async def create_team(
    session: AsyncSession, data: TeamCreate, *, actor: User, today: date, horizon_days: int, ip: str | None
) -> Team:
    """Новая команда сразу получает периоды общих платежей — с ближайшего срока, без долгов за прошлое."""
    await _ensure_name_free(session, data.name)
    team = Team(name=data.name, telegram_chat_id=data.telegram_chat_id)
    session.add(team)
    await _flush_unique(session, data.name)
    await session.refresh(team)  # created_at из базы: с него считаются сроки общих платежей
    await ensure_occurrences(session, today=today, horizon_days=horizon_days)
    audit.record(
        session, AuditAction.TEAM_CREATE, actor=actor, entity=("team", team.id), details={"name": team.name}, ip=ip
    )
    await session.commit()
    return team


async def get_team(session: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise not_found("Команда не найдена")
    return team


async def update_team(
    session: AsyncSession, team_id: uuid.UUID, data: TeamUpdate, *, actor: User, ip: str | None
) -> Team:
    team = await get_team(session, team_id)
    changes = data.model_dump(exclude_unset=True)
    if data.name is not None:
        await _ensure_name_free(session, data.name, except_id=team.id)
        team.name = data.name
    if "telegram_chat_id" in changes:
        team.telegram_chat_id = data.telegram_chat_id
    await _flush_unique(session, team.name)
    audit.record(
        session,
        AuditAction.TEAM_UPDATE,
        actor=actor,
        entity=("team", team.id),
        details={"name": team.name, "telegram_chat_id": team.telegram_chat_id},
        ip=ip,
    )
    await session.commit()
    return team


async def delete_team(session: AsyncSession, team_id: uuid.UUID, *, actor: User, ip: str | None) -> None:
    """Удаляется только пустая команда: без участников, своих платежей, оплат и чеков — история не теряется.
    Её неоплаченные периоды общих платежей и бюджеты уходят вместе с ней."""
    team = await get_team(session, team_id)
    team_occurrences = PaymentOccurrence.team_id == team.id
    used = await session.scalar(
        select(
            exists().where(User.team_id == team.id)
            | exists().where(RecurringPayment.team_id == team.id)
            | exists().where(team_occurrences, PaymentOccurrence.status == OccurrenceStatus.PAID)
            | exists().where(Attachment.occurrence_id == PaymentOccurrence.id, team_occurrences)
        )
    )
    if used:
        raise AppError(status.HTTP_409_CONFLICT, "team_not_empty", NOT_EMPTY)
    name = team.name
    await session.delete(team)
    await session.flush()
    audit.record(session, AuditAction.TEAM_DELETE, actor=actor, entity=("team", team_id), details={"name": name}, ip=ip)
    await session.commit()
