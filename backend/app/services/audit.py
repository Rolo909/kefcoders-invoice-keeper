import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

ACTOR_LOGIN_MAX_LENGTH = 64


class AuditAction(StrEnum):
    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    PAYMENT_CREATE = "payment.create"
    PAYMENT_DELETE = "payment.delete"
    OCCURRENCE_MARK_PAID = "occurrence.mark_paid"
    OCCURRENCE_MARK_UNPAID = "occurrence.mark_unpaid"
    OCCURRENCE_CHANGE_PAID_DATE = "occurrence.change_paid_date"
    TELEGRAM_MARK_PAID = "telegram.mark_paid"
    BUDGET_UPDATE = "budget.update"
    CALENDAR_LINK_CREATE = "calendar.link_create"
    CALENDAR_LINK_REVOKE = "calendar.link_revoke"
    ATTACHMENT_ADD = "attachment.add"
    ATTACHMENT_DELETE = "attachment.delete"


def record(
    session: AsyncSession,
    action: AuditAction,
    *,
    actor: User | None,
    actor_login: str | None = None,
    entity: tuple[str, uuid.UUID] | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    at: datetime | None = None,
) -> None:
    """Добавляет запись журнала в текущую транзакцию — она сохранится вместе с самим действием.

    at — время события, если оно было раньше записи (тестовые данные); обычно не передаётся.
    """
    login = actor.login if actor is not None else (actor_login or "")
    entity_type, entity_id = entity if entity is not None else (None, None)
    session.add(
        AuditLog(
            # clock_timestamp(), а не now(): now() — время начала транзакции, и несколько действий
            # в одной транзакции получили бы одно время и потеряли порядок.
            at=at if at is not None else func.clock_timestamp(),
            actor_id=actor.id if actor is not None else None,
            actor_login=login[:ACTOR_LOGIN_MAX_LENGTH],
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip=ip,
        )
    )
