"""Регулярные платежи: создание, прекращение с сохранением истории, списки."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import status
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Currency, OccurrenceStatus
from app.errors import AppError, not_found
from app.models import PaymentOccurrence, RecurringPayment, User
from app.schemas.payment import RecurringPaymentCreate
from app.services import audit
from app.services.audit import AuditAction
from app.services.occurrences import OccurrenceView, ensure_occurrences, payment_views, views_by_ids

# Защита от случайной даты в далёком прошлом: каждая неделя/месяц стали бы просроченным периодом.
MAX_PAST_DAYS = 366


@dataclass(frozen=True)
class PaymentView:
    payment: RecurringPayment
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
    payment = RecurringPayment(
        name=data.name,
        description=data.description,
        amount=data.amount,
        currency=data.currency,
        period=data.period,
        first_due_date=data.next_due_date,
        end_date=data.end_date,
        created_by=actor.id,
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
    session: AsyncSession, payment_ids: list[uuid.UUID], today: date
) -> dict[uuid.UUID, uuid.UUID]:
    """Ближайший период: самый ранний неоплаченный, а если все оплачены — ближайший будущий."""
    occ = PaymentOccurrence
    priority = case((occ.status == OccurrenceStatus.UNPAID, 0), else_=1)
    rows = await session.execute(
        select(occ.recurring_payment_id, occ.id)
        .where(
            occ.recurring_payment_id.in_(payment_ids),
            (occ.status == OccurrenceStatus.UNPAID) | (occ.due_date >= today),
        )
        .ext(distinct_on(occ.recurring_payment_id))
        .order_by(occ.recurring_payment_id, priority, occ.due_date)
    )
    return {payment_id: occurrence_id for payment_id, occurrence_id in rows}


async def list_payments(
    session: AsyncSession, *, include_deleted: bool, currency: Currency | None, query: str | None, today: date
) -> list[PaymentView]:
    """Сначала действующие платежи, внутри — по ближайшему сроку; затем прекращённые."""
    stmt = select(RecurringPayment, User).join(User, User.id == RecurringPayment.created_by)
    if not include_deleted:
        stmt = stmt.where(RecurringPayment.deleted_at.is_(None))
    if currency is not None:
        stmt = stmt.where(RecurringPayment.currency == currency)
    if query:
        stmt = stmt.where(RecurringPayment.name.icontains(query.strip(), autoescape=True))
    rows = (await session.execute(stmt)).all()

    next_ids = await _next_occurrence_ids(session, [p.id for p, _ in rows], today)
    next_views = await views_by_ids(session, list(next_ids.values()))
    views = [PaymentView(p, author, next_views[next_ids[p.id]] if p.id in next_ids else None) for p, author in rows]

    def sort_key(view: PaymentView) -> tuple[bool, date, str]:
        next_due = view.next_occurrence.occurrence.due_date if view.next_occurrence else date.max
        return view.payment.deleted_at is not None, next_due, view.payment.name.lower()

    return sorted(views, key=sort_key)


async def get_payment(
    session: AsyncSession, payment_id: uuid.UUID, *, today: date
) -> tuple[PaymentView, list[OccurrenceView]]:
    row = (
        await session.execute(
            select(RecurringPayment, User)
            .join(User, User.id == RecurringPayment.created_by)
            .where(RecurringPayment.id == payment_id)
        )
    ).first()
    if row is None:
        raise not_found("Платёж не найден")
    payment, author = row
    occurrences = await payment_views(session, payment_id)
    next_ids = await _next_occurrence_ids(session, [payment_id], today)
    next_view = next((v for v in occurrences if v.occurrence.id == next_ids.get(payment_id)), None)
    return PaymentView(payment, author, next_view), occurrences
