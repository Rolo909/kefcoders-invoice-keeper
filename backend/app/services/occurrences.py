"""Периоды регулярных платежей: создание по расписанию, выборки с вычисляемыми полями, отметка оплаты."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import ColumnElement, Date, Select, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.config import get_settings
from app.domain.enums import (
    Currency,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    OccurrenceState,
    OccurrenceStatus,
)
from app.domain.schedule import due_date, first_seq_on_or_after
from app.errors import AppError, not_found
from app.models import Attachment, AuditLog, Notification, PaymentOccurrence, RecurringPayment, Team, User
from app.services import audit
from app.services.audit import AuditAction

Occ = PaymentOccurrence
PaidBy = aliased(User, name="paid_by_user")


# ---------- создание периодов по расписанию ----------


def missing_occurrences(
    payment: RecurringPayment,
    *,
    team_id: uuid.UUID,
    last_seq: int | None,
    last_due: date | None,
    today: date,
    horizon_days: int,
    start: date | None = None,
) -> list[dict[str, Any]]:
    """Периоды команды, которых не хватает: все сроки до today + horizon и всегда хотя бы один будущий срок.

    Статус прошлых периодов на создание следующих не влияет — просрочка не останавливает расписание.
    start — первый допустимый срок (команда подключилась к общему платежу позже его создания).
    """
    horizon_end = today + timedelta(days=horizon_days)
    if last_seq is not None:
        seq = last_seq + 1
    else:
        seq = 0 if start is None else first_seq_on_or_after(payment.first_due_date, payment.period, start)
    has_future = last_due is not None and last_due > today
    rows: list[dict[str, Any]] = []
    while True:
        due = due_date(payment.first_due_date, payment.period, seq)
        if payment.end_date is not None and due > payment.end_date:
            break
        if due > horizon_end and has_future:
            break
        rows.append(
            {
                "id": uuid.uuid4(),
                "recurring_payment_id": payment.id,
                "team_id": team_id,
                "seq": seq,
                "due_date": due,
                "amount": payment.amount,
                "currency": payment.currency,
            }
        )
        has_future = has_future or due > today
        seq += 1
    return rows


async def _insert_occurrences(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    if rows:
        # ON CONFLICT: параллельный запуск (API и worker) не создаст период дважды.
        await session.execute(
            pg_insert(Occ)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["recurring_payment_id", "team_id", "seq"])
        )


def team_start(payment: RecurringPayment, team: Team, timezone: ZoneInfo) -> date | None:
    """С какого срока команда платит общий платёж: если она появилась позже платежа — со дня своего создания.

    Так у новой команды нет «долгов» за сроки, прошедшие до неё. Платёж команды — со своего первого срока.
    """
    if payment.team_id is not None:
        return None
    joined = team.created_at.astimezone(timezone).date()
    return joined if joined > payment.created_at.astimezone(timezone).date() else None


async def ensure_occurrences(
    session: AsyncSession,
    payments: Sequence[RecurringPayment] | None = None,
    *,
    today: date,
    horizon_days: int,
    timezone: ZoneInfo | None = None,
) -> None:
    """Досоздаёт недостающие периоды активных платежей (всех или переданных) у их команд. Идемпотентно.

    Платёж команды — периоды только у неё; общий платёж (team_id = null) — у каждой команды.
    """
    tz = timezone or get_settings().timezone
    stmt = (
        select(RecurringPayment, Team, func.max(Occ.seq), func.max(Occ.due_date))
        .join(Team, or_(RecurringPayment.team_id == Team.id, RecurringPayment.team_id.is_(None)))
        .outerjoin(Occ, and_(Occ.recurring_payment_id == RecurringPayment.id, Occ.team_id == Team.id))
        .where(RecurringPayment.deleted_at.is_(None), RecurringPayment.is_active)
        .group_by(RecurringPayment.id, Team.id)
    )
    if payments is not None:
        stmt = stmt.where(RecurringPayment.id.in_([p.id for p in payments]))
    rows: list[dict[str, Any]] = []
    for payment, team, last_seq, last_due in await session.execute(stmt):
        rows += missing_occurrences(
            payment,
            team_id=team.id,
            last_seq=last_seq,
            last_due=last_due,
            today=today,
            horizon_days=horizon_days,
            start=team_start(payment, team, tz),
        )
    await _insert_occurrences(session, rows)


# ---------- выборки ----------


@dataclass(frozen=True)
class OccurrenceView:
    occurrence: PaymentOccurrence
    payment: RecurringPayment
    paid_by: User | None
    attachments_count: int
    last_reminder_at: datetime | None


@dataclass(frozen=True)
class OccurrenceDetail:
    view: OccurrenceView
    history: list[tuple[AuditLog, User | None]]
    reminders: list[Notification]


@dataclass(frozen=True)
class OccurrenceFilter:
    status: OccurrenceStatus | None = None
    overdue: bool | None = None
    state: OccurrenceState | None = None
    date_from: date | None = None
    date_to: date | None = None
    currencies: list[Currency] = field(default_factory=list)
    recurring_payment_id: uuid.UUID | None = None


SORT_FIELDS = ("due_date", "amount", "days_overdue")


def _today(today: date) -> ColumnElement[date]:
    return literal(today, Date)


def overdue_condition(today: date) -> ColumnElement[bool]:
    """SQL-аналог domain.status.is_overdue — фильтр работает так же, как вычисляемое поле."""
    return or_(
        and_(Occ.status == OccurrenceStatus.UNPAID, Occ.due_date < _today(today)),
        and_(Occ.status == OccurrenceStatus.PAID, Occ.paid_date > Occ.due_date),
    )


def state_condition(state: OccurrenceState, today: date, remind_days_before: int) -> ColumnElement[bool]:
    """SQL-аналог domain.status.occurrence_state."""
    unpaid = Occ.status == OccurrenceStatus.UNPAID
    soon_limit = literal(today + timedelta(days=remind_days_before), Date)
    conditions: dict[OccurrenceState, ColumnElement[bool]] = {
        OccurrenceState.PAID: and_(Occ.status == OccurrenceStatus.PAID, Occ.paid_date <= Occ.due_date),
        OccurrenceState.PAID_LATE: and_(Occ.status == OccurrenceStatus.PAID, Occ.paid_date > Occ.due_date),
        OccurrenceState.OVERDUE: and_(unpaid, Occ.due_date < _today(today)),
        OccurrenceState.DUE_SOON: and_(unpaid, Occ.due_date >= _today(today), Occ.due_date <= soon_limit),
        OccurrenceState.UPCOMING: and_(unpaid, Occ.due_date > soon_limit),
    }
    return conditions[state]


def _days_overdue(today: date) -> ColumnElement[int]:
    # paid_date есть только у оплаченных — для неоплаченных просрочка считается до сегодня.
    return func.greatest(0, func.coalesce(Occ.paid_date, _today(today)) - Occ.due_date)


def _view_query() -> Select[Any]:
    attachments_count = (
        select(func.count(Attachment.id)).where(Attachment.occurrence_id == Occ.id).correlate(Occ).scalar_subquery()
    )
    last_reminder_at = (
        select(func.max(Notification.sent_at))
        .where(
            Notification.occurrence_id == Occ.id,
            Notification.channel == NotificationChannel.TELEGRAM,
            Notification.kind == NotificationKind.BEFORE_DUE,
            Notification.status == NotificationStatus.SENT,
        )
        .correlate(Occ)
        .scalar_subquery()
    )
    return (
        select(Occ, RecurringPayment, PaidBy, attachments_count, last_reminder_at)
        .join(RecurringPayment, RecurringPayment.id == Occ.recurring_payment_id)
        .outerjoin(PaidBy, PaidBy.id == Occ.paid_by)
    )


async def _load_views(session: AsyncSession, stmt: Select[Any]) -> list[OccurrenceView]:
    return [
        OccurrenceView(occurrence=o, payment=p, paid_by=u, attachments_count=count or 0, last_reminder_at=reminded)
        for o, p, u, count, reminded in await session.execute(stmt)
    ]


def _filter_conditions(filters: OccurrenceFilter, today: date, remind_days_before: int) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.status is not None:
        conditions.append(Occ.status == filters.status)
    if filters.overdue is not None:
        overdue = overdue_condition(today)
        conditions.append(overdue if filters.overdue else ~overdue)
    if filters.state is not None:
        conditions.append(state_condition(filters.state, today, remind_days_before))
    if filters.date_from is not None:
        conditions.append(Occ.due_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Occ.due_date <= filters.date_to)
    if filters.currencies:
        conditions.append(Occ.currency.in_(filters.currencies))
    if filters.recurring_payment_id is not None:
        conditions.append(Occ.recurring_payment_id == filters.recurring_payment_id)
    return conditions


def _order_by(sort: str, today: date) -> list[Any]:
    key = sort.removeprefix("-")
    column: ColumnElement[Any] | InstrumentedAttribute[Any]
    if key == "amount":
        column = Occ.amount
    elif key == "days_overdue":
        column = _days_overdue(today)
    else:
        column = Occ.due_date
    return [column.desc() if sort.startswith("-") else column.asc(), RecurringPayment.name, Occ.id]


async def list_occurrences(
    session: AsyncSession,
    filters: OccurrenceFilter,
    *,
    sort: str,
    limit: int,
    offset: int,
    today: date,
    remind_days_before: int,
) -> tuple[list[OccurrenceView], int]:
    conditions = _filter_conditions(filters, today, remind_days_before)
    total = await session.scalar(select(func.count()).select_from(Occ).where(*conditions)) or 0
    stmt = _view_query().where(*conditions).order_by(*_order_by(sort, today)).limit(limit).offset(offset)
    return await _load_views(session, stmt), total


async def views_by_ids(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, OccurrenceView]:
    if not ids:
        return {}
    views = await _load_views(session, _view_query().where(Occ.id.in_(ids)))
    return {view.occurrence.id: view for view in views}


async def payment_views(session: AsyncSession, payment_id: uuid.UUID) -> list[OccurrenceView]:
    """Все периоды платежа, новые сверху."""
    stmt = _view_query().where(Occ.recurring_payment_id == payment_id).order_by(Occ.due_date.desc())
    return await _load_views(session, stmt)


async def views_between(session: AsyncSession, start: date, end: date) -> list[OccurrenceView]:
    """Все периоды со сроком в [start, end] — для календаря, по сроку и названию."""
    stmt = _view_query().where(Occ.due_date.between(start, end)).order_by(Occ.due_date, RecurringPayment.name, Occ.id)
    return await _load_views(session, stmt)


async def _get_view(session: AsyncSession, occurrence_id: uuid.UUID) -> OccurrenceView:
    views = await views_by_ids(session, [occurrence_id])
    if occurrence_id not in views:
        raise not_found("Период не найден")
    return views[occurrence_id]


async def get_occurrence_detail(session: AsyncSession, occurrence_id: uuid.UUID) -> OccurrenceDetail:
    view = await _get_view(session, occurrence_id)
    history = (
        await session.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .where(AuditLog.entity_type == "occurrence", AuditLog.entity_id == occurrence_id)
            .order_by(AuditLog.at, AuditLog.id)
        )
    ).all()
    reminders = await session.scalars(
        select(Notification).where(Notification.occurrence_id == occurrence_id).order_by(Notification.created_at.desc())
    )
    return OccurrenceDetail(view=view, history=list(history), reminders=list(reminders))


# ---------- отметка оплаты ----------


def _details(view: OccurrenceView, **extra: date | None) -> dict[str, str | None]:
    values = {"due_date": view.occurrence.due_date, **extra}
    return {"payment_name": view.payment.name} | {k: v.isoformat() if v else None for k, v in values.items()}


def already_paid(paid_by: User | None, paid_date: date | None) -> AppError:
    """Повторная отметка оплаты: сообщаем, кто и когда уже оплатил, чтобы не заплатить дважды."""
    who = (paid_by.full_name or paid_by.login) if paid_by else "другой пользователь"
    when = paid_date.strftime("%d.%m.%Y") if paid_date else "—"
    return AppError(status.HTTP_409_CONFLICT, "already_paid", f"Уже оплачено: {who}, {when}. Обновите страницу.")


def _validation_error(detail: str) -> AppError:
    return AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", detail)


async def update_occurrence(
    session: AsyncSession,
    occurrence_id: uuid.UUID,
    *,
    new_status: OccurrenceStatus | None,
    paid_date: date | None,
    actor: User,
    today: date,
    now: datetime,
    ip: str | None,
) -> OccurrenceView:
    """Отметить оплату / отменить её / исправить фактическую дату. Срок периода не меняется никогда.

    status=paid — только для неоплаченного периода (иначе 409 already_paid); дату оплаченного
    исправляют запросом с одной paid_date.
    """
    if new_status is None and paid_date is None:
        raise _validation_error("Передайте status или paid_date")
    if paid_date is not None and paid_date > today:
        raise _validation_error("Дата оплаты не может быть позже сегодняшней")

    # Блокировка строки: два одновременных изменения одного периода выполняются по очереди.
    await session.execute(select(Occ.id).where(Occ.id == occurrence_id).with_for_update())
    view = await _get_view(session, occurrence_id)
    occurrence = view.occurrence
    old_paid_date = occurrence.paid_date
    entity = ("occurrence", occurrence.id)

    def log(action: AuditAction, **extra: date | None) -> None:
        audit.record(session, action, actor=actor, entity=entity, details=_details(view, **extra), ip=ip)

    if new_status is OccurrenceStatus.UNPAID:
        occurrence.status = OccurrenceStatus.UNPAID
        occurrence.paid_date = occurrence.paid_by = occurrence.paid_marked_at = None
        log(AuditAction.OCCURRENCE_MARK_UNPAID, old_paid_date=old_paid_date)
    elif occurrence.status is OccurrenceStatus.PAID and new_status is OccurrenceStatus.PAID:
        # Кто-то уже отметил оплату (например, одновременно с вами) — не перезаписываем молча.
        raise already_paid(view.paid_by, occurrence.paid_date)
    elif occurrence.status is OccurrenceStatus.PAID:  # передана только paid_date — исправление даты
        new_date = paid_date or today
        if new_date != old_paid_date:
            occurrence.paid_date = new_date
            log(AuditAction.OCCURRENCE_CHANGE_PAID_DATE, old_paid_date=old_paid_date, new_paid_date=new_date)
    elif new_status is OccurrenceStatus.PAID:
        occurrence.status = OccurrenceStatus.PAID
        occurrence.paid_date = paid_date or today
        occurrence.paid_by = actor.id
        occurrence.paid_marked_at = now
        log(AuditAction.OCCURRENCE_MARK_PAID, paid_date=occurrence.paid_date)
    else:
        raise AppError(status.HTTP_409_CONFLICT, "not_paid", "Сначала отметьте оплату, потом меняйте дату")

    await session.commit()
    return await _get_view(session, occurrence_id)
