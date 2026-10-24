"""Плановые сроки, для которых периоды ещё не созданы (дальше горизонта)."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.schedule import occurrences_between
from app.models import PaymentOccurrence, RecurringPayment


@dataclass(frozen=True)
class PlannedDue:
    payment: RecurringPayment
    seq: int
    due_date: date


async def planned_between(session: AsyncSession, start: date, end: date) -> list[PlannedDue]:
    """Сроки действующих платежей в [start, end], которых ещё нет среди созданных периодов.

    Периоды действующего платежа создаются подряд с номера 0, поэтому «не создан» — это номер больше
    максимального созданного.
    """
    rows = await session.execute(
        select(RecurringPayment, func.max(PaymentOccurrence.seq))
        .outerjoin(PaymentOccurrence, PaymentOccurrence.recurring_payment_id == RecurringPayment.id)
        .where(RecurringPayment.deleted_at.is_(None), RecurringPayment.is_active)
        .group_by(RecurringPayment.id)
    )
    planned: list[PlannedDue] = []
    for payment, last_seq in rows:
        last_created = -1 if last_seq is None else last_seq
        planned += [
            PlannedDue(payment, seq, due)
            for seq, due in occurrences_between(
                payment.first_due_date, payment.period, start, end, until=payment.end_date
            )
            if seq > last_created
        ]
    return planned
