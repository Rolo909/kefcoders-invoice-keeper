"""Плановые сроки, для которых периоды ещё не созданы (дальше горизонта), — по каждой команде."""

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.schedule import first_seq_on_or_after, occurrences_between
from app.models import PaymentOccurrence, RecurringPayment, Team
from app.services.occurrences import team_start
from app.services.scope import TeamScope


@dataclass(frozen=True)
class PlannedDue:
    payment: RecurringPayment
    team: Team
    seq: int
    due_date: date


async def planned_between(
    session: AsyncSession, start: date, end: date, scope: TeamScope, *, timezone: ZoneInfo | None = None
) -> list[PlannedDue]:
    """Сроки действующих платежей видимых команд в [start, end], которых ещё нет среди созданных периодов.

    Периоды команды создаются подряд, поэтому «не создан» — это номер больше максимального созданного.
    Общий платёж планируется у каждой команды, у новой команды — со дня её создания.
    """
    tz = timezone or get_settings().timezone
    rows = await session.execute(
        select(RecurringPayment, Team, func.max(PaymentOccurrence.seq))
        .join(Team, or_(RecurringPayment.team_id == Team.id, RecurringPayment.team_id.is_(None)))
        .outerjoin(
            PaymentOccurrence,
            and_(PaymentOccurrence.recurring_payment_id == RecurringPayment.id, PaymentOccurrence.team_id == Team.id),
        )
        .where(RecurringPayment.deleted_at.is_(None), RecurringPayment.is_active, *scope.where(Team.id))
        .group_by(RecurringPayment.id, Team.id)
    )
    planned: list[PlannedDue] = []
    for payment, team, last_seq in rows:
        joined = team_start(payment, team, tz)
        first = 0 if joined is None else first_seq_on_or_after(payment.first_due_date, payment.period, joined)
        last_created = first - 1 if last_seq is None else last_seq
        planned += [
            PlannedDue(payment, team, seq, due)
            for seq, due in occurrences_between(
                payment.first_due_date, payment.period, start, end, until=payment.end_date
            )
            if seq > last_created
        ]
    return planned
