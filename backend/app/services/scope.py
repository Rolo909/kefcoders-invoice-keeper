"""Какие команды видит запрос — единственное место, где решается изоляция команд.

Пользователь видит только свою команду: её периоды, её платежи и общие платежи. Чужой объект для него
не существует (404, а не 403 — не раскрываем, что он есть), чужая команда в фильтре — 403.
Администратор видит все команды; team_id сужает списки, но конкретный объект он открывает всегда.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.domain.enums import Role
from app.errors import forbidden, not_found
from app.models import Attachment, PaymentOccurrence, RecurringPayment, Team, User

FOREIGN_TEAM = "Данные другой команды недоступны"


@dataclass(frozen=True)
class TeamScope:
    # None — все команды; иначе — набор видимых команд (пустой у пользователя без команды).
    team_ids: frozenset[uuid.UUID] | None
    is_admin: bool

    def where(
        self, column: InstrumentedAttribute[uuid.UUID] | InstrumentedAttribute[uuid.UUID | None]
    ) -> list[ColumnElement[bool]]:
        """Условия для выборки по колонке team_id (периоды, бюджеты, пользователи)."""
        return [] if self.team_ids is None else [column.in_(self.team_ids)]

    def payments_where(self) -> list[ColumnElement[bool]]:
        """Платежи команды и общие (team_id = null)."""
        if self.team_ids is None:
            return []
        return [or_(RecurringPayment.team_id.is_(None), RecurringPayment.team_id.in_(self.team_ids))]

    def sees_team(self, team_id: uuid.UUID) -> bool:
        return self.team_ids is None or team_id in self.team_ids

    def can_open_occurrence(self, occurrence: PaymentOccurrence) -> bool:
        return self.is_admin or self.sees_team(occurrence.team_id)

    def can_open_payment(self, payment: RecurringPayment) -> bool:
        return self.is_admin or payment.team_id is None or self.sees_team(payment.team_id)


async def resolve_scope(session: AsyncSession, actor: User, team_id: uuid.UUID | None) -> TeamScope:
    """Область видимости запроса с необязательным фильтром team_id."""
    if actor.role is Role.ADMIN:
        if team_id is None:
            return TeamScope(team_ids=None, is_admin=True)
        if await session.get(Team, team_id) is None:
            raise not_found("Команда не найдена")
        return TeamScope(team_ids=frozenset({team_id}), is_admin=True)
    if team_id is not None and team_id != actor.team_id:
        raise forbidden(FOREIGN_TEAM)
    return TeamScope(team_ids=frozenset() if actor.team_id is None else frozenset({actor.team_id}), is_admin=False)


async def visible_occurrence(session: AsyncSession, scope: TeamScope, occurrence_id: uuid.UUID) -> PaymentOccurrence:
    occurrence = await session.get(PaymentOccurrence, occurrence_id)
    if occurrence is None or not scope.can_open_occurrence(occurrence):
        raise not_found("Период не найден")
    return occurrence


async def visible_payment(session: AsyncSession, scope: TeamScope, payment_id: uuid.UUID) -> RecurringPayment:
    payment = await session.get(RecurringPayment, payment_id)
    if payment is None or not scope.can_open_payment(payment):
        raise not_found("Платёж не найден")
    return payment


async def visible_attachment(session: AsyncSession, scope: TeamScope, attachment_id: uuid.UUID) -> Attachment:
    row = (
        await session.execute(
            select(Attachment, PaymentOccurrence)
            .join(PaymentOccurrence, PaymentOccurrence.id == Attachment.occurrence_id)
            .where(Attachment.id == attachment_id)
        )
    ).first()
    if row is None or not scope.can_open_occurrence(row[1]):
        raise not_found("Вложение не найдено")
    attachment: Attachment = row[0]
    return attachment
