"""Регулярные платежи: создание, прекращение с сохранением истории, списки."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import status
from sqlalchemy import ColumnElement, case, delete, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Currency, OccurrenceStatus
from app.errors import AppError, not_found
from app.models import PaymentOccurrence, RecurringPayment, Team, User
from app.schemas.payment import RecurringPaymentCreate
from app.services import audit
from app.services.audit import AuditAction
from app.services.occurrences import OccurrenceView, ensure_occurrences, payment_views, views_by_ids
from app.services.scope import TeamScope, visible_payment
from app.services.users import get_team_or_422

# Защита от случайной даты в далёком прошлом: каждая неделя/месяц стали бы просроченным периодом.
MAX_PAST_DAYS = 366


@dataclass(frozen=True)
class PaymentView:
    payment: RecurringPayment
    team: Team | None
    created_by: User
    next_occurrence: OccurrenceView | None


async def create_payment(
    session: AsyncSession,
    data: RecurringPaymentCreate,
    *,
    actor: User,
    today: date,
    horizon_days: int,
    ip: str | None,
) -> RecurringPayment:
    if data.next_due_date < today - timedelta(days=MAX_PAST_DAYS):
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "Дата ближайшей оплаты — не раньше чем год назад",
        )
    team = None if data.team_id is None else await get_team_or_422(session, data.team_id)
    payment = RecurringPayment(
        name=data.name,
        description=data.description,
        amount=data.amount,
        currency=data.currency,
        period=data.period,
        first_due_date=data.next_due_date,
        end_date=data.end_date,
        created_by=actor.id,
        team_id=None if team is None else team.id,
    )
    session.add(payment)
    await session.flush()
    await ensure_occurrences(session, [payment], today=today, horizon_days=horizon_days)
    audit.record(
        session,
        AuditAction.PAYMENT_CREATE,
        actor=actor,
        entity=("recurring_payment", payment.id),
        details={
            "payment_name": payment.name,
            "amount": str(payment.amount),
            "currency": payment.currency.value,
            "period": payment.period.value,
            "first_due_date": payment.first_due_date.isoformat(),
            "team_name": None if team is None else team.name,
        },
        ip=ip,
    )
    await session.commit()
    return payment


async def stop_payment(
    session: AsyncSession, payment_id: uuid.UUID, *, actor: User, today: date, now: datetime, ip: str | None
) -> None:
    """Прекращение: прошлые и оплаченные периоды остаются в истории, будущие неоплаченные удаляются
    вместе с их напоминаниями. Повторный вызов ничего не меняет."""
    payment = await session.get(RecurringPayment, payment_id, with_for_update=True)
    if payment is None:
        raise not_found("Платёж не найден")
    if payment.deleted_at is not None:
        return
    payment.deleted_at = now
    payment.is_active = False
    removed = await session.execute(
        delete(PaymentOccurrence)
        .where(
            PaymentOccurrence.recurring_payment_id == payment.id,
            PaymentOccurrence.due_date > today,
            PaymentOccurrence.status == OccurrenceStatus.UNPAID,
        )
        .returning(PaymentOccurrence.id)
    )
    audit.record(
        session,
        AuditAction.PAYMENT_DELETE,
        actor=actor,
        entity=("recurring_payment", payment.id),
        details={"payment_name": payment.name, "removed_periods": len(removed.all())},
        ip=ip,
    )
    await session.commit()


async def _next_occurrence_ids(
    session: AsyncSession,
    payment_ids: list[uuid.UUID],
    today: date,
    team_conditions: Sequence[ColumnElement[bool]] = (),
) -> dict[uuid.UUID, uuid.UUID]:
    """Ближайший период среди видимых команд: самый ранний неоплаченный, а если все оплачены — ближайший
    будущий. У общего платежа в режиме «все команды» — самый ранний из команд."""
    occ = PaymentOccurrence
    priority = case((occ.status == OccurrenceStatus.UNPAID, 0), else_=1)
    rows = await session.execute(
        select(occ.recurring_payment_id, occ.id)
        .where(
            occ.recurring_payment_id.in_(payment_ids),
            (occ.status == OccurrenceStatus.UNPAID) | (occ.due_date >= today),
            *team_conditions,
        )
        .ext(distinct_on(occ.recurring_payment_id))
        .order_by(occ.recurring_payment_id, priority, occ.due_date)
    )
    return {payment_id: occurrence_id for payment_id, occurrence_id in rows}


async def list_payments(
    session: AsyncSession,
    *,
    include_deleted: bool,
    currency: Currency | None,
    query: str | None,
    today: date,
    scope: TeamScope,
) -> list[PaymentView]:
    """Платежи видимых команд и общие. Сначала действующие, внутри — по ближайшему сроку; затем прекращённые."""
    stmt = (
        select(RecurringPayment, Team, User)
        .join(User, User.id == RecurringPayment.created_by)
        .outerjoin(Team, Team.id == RecurringPayment.team_id)
        .where(*scope.payments_where())
    )
    if not include_deleted:
        stmt = stmt.where(RecurringPayment.deleted_at.is_(None))
    if currency is not None:
        stmt = stmt.where(RecurringPayment.currency == currency)
    if query:
        stmt = stmt.where(RecurringPayment.name.icontains(query.strip(), autoescape=True))
    rows = (await session.execute(stmt)).all()

    team_conditions = scope.where(PaymentOccurrence.team_id)
    next_ids = await _next_occurrence_ids(session, [p.id for p, _, _ in rows], today, team_conditions)
    next_views = await views_by_ids(session, list(next_ids.values()))
    views = [
        PaymentView(p, team, author, next_views[next_ids[p.id]] if p.id in next_ids else None)
        for p, team, author in rows
    ]

    def sort_key(view: PaymentView) -> tuple[bool, date, str]:
        next_due = view.next_occurrence.occurrence.due_date if view.next_occurrence else date.max
        return view.payment.deleted_at is not None, next_due, view.payment.name.lower()

    return sorted(views, key=sort_key)


async def get_payment(
    session: AsyncSession, payment_id: uuid.UUID, *, today: date, scope: TeamScope
) -> tuple[PaymentView, list[OccurrenceView]]:
    """Платёж с периодами. У платежа команды — всегда её периоды (администратор мог открыть его по ссылке,
    выбрав другую команду); у общего — периоды видимых команд."""
    payment = await visible_payment(session, scope, payment_id)
    author = (await session.scalars(select(User).where(User.id == payment.created_by))).one()
    team_conditions = [] if payment.team_id is not None else scope.where(PaymentOccurrence.team_id)
    occurrences = await payment_views(session, payment_id, team_conditions)
    next_ids = await _next_occurrence_ids(session, [payment_id], today, team_conditions)
    next_view = next((v for v in occurrences if v.occurrence.id == next_ids.get(payment_id)), None)
    team = None if payment.team_id is None else await session.get(Team, payment.team_id)
    return PaymentView(payment, team, author, next_view), occurrences
