"""Преобразование результатов сервисов в схемы ответа API."""

from datetime import date

from app.domain.status import days_overdue, is_overdue, occurrence_state
from app.models import AuditLog, Notification, User
from app.schemas.payment import (
    AuditLogOut,
    NotificationLogOut,
    OccurrenceDetailOut,
    OccurrenceOut,
    PaymentBrief,
    RecurringPaymentDetailOut,
    RecurringPaymentOut,
)
from app.schemas.user import UserBrief
from app.services.occurrences import OccurrenceDetail, OccurrenceView
from app.services.payments import PaymentView


def occurrence_out(view: OccurrenceView, *, today: date, remind_days_before: int) -> OccurrenceOut:
    o, p = view.occurrence, view.payment
    return OccurrenceOut(
        id=o.id,
        recurring_payment_id=p.id,
        recurring_payment=PaymentBrief(id=p.id, name=p.name, period=p.period, is_deleted=p.deleted_at is not None),
        seq=o.seq,
        due_date=o.due_date,
        amount=o.amount,
        currency=o.currency,
        status=o.status,
        paid_date=o.paid_date,
        paid_by=UserBrief.model_validate(view.paid_by) if view.paid_by else None,
        paid_marked_at=o.paid_marked_at,
        note=o.note,
        is_overdue=is_overdue(o, today),
        state=occurrence_state(o, today, remind_days_before),
        days_overdue=days_overdue(o, today),
        attachments_count=view.attachments_count,
        last_reminder_at=view.last_reminder_at,
    )


def occurrence_detail_out(detail: OccurrenceDetail, *, today: date, remind_days_before: int) -> OccurrenceDetailOut:
    base = occurrence_out(detail.view, today=today, remind_days_before=remind_days_before)
    o, p = detail.view.occurrence, detail.view.payment
    return OccurrenceDetailOut(
        **base.model_dump(),
        history=[audit_log_out(log, actor) for log, actor in detail.history],
        reminders=[notification_out(n, payment_name=p.name, due_date=o.due_date) for n in detail.reminders],
    )


def audit_log_out(log: AuditLog, actor: User | None) -> AuditLogOut:
    return AuditLogOut(
        id=log.id,
        at=log.at,
        actor=UserBrief.model_validate(actor) if actor else None,
        actor_login=log.actor_login,
        action=log.action,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        details=log.details,
        ip=log.ip,
    )


def notification_out(n: Notification, *, payment_name: str, due_date: date) -> NotificationLogOut:
    return NotificationLogOut(
        id=n.id,
        occurrence_id=n.occurrence_id,
        payment_name=payment_name,
        due_date=due_date,
        channel=n.channel,
        kind=n.kind,
        status=n.status,
        attempts=n.attempts,
        last_error=n.last_error,
        sent_at=n.sent_at,
        created_at=n.created_at,
    )


def payment_out(view: PaymentView, *, today: date, remind_days_before: int) -> RecurringPaymentOut:
    p = view.payment
    next_occurrence = view.next_occurrence
    return RecurringPaymentOut(
        id=p.id,
        name=p.name,
        description=p.description,
        amount=p.amount,
        currency=p.currency,
        period=p.period,
        first_due_date=p.first_due_date,
        end_date=p.end_date,
        is_active=p.is_active,
        deleted_at=p.deleted_at,
        created_by=UserBrief.model_validate(view.created_by),
        created_at=p.created_at,
        next_occurrence=(
            occurrence_out(next_occurrence, today=today, remind_days_before=remind_days_before)
            if next_occurrence
            else None
        ),
    )


def payment_detail_out(
    view: PaymentView, occurrences: list[OccurrenceView], *, today: date, remind_days_before: int
) -> RecurringPaymentDetailOut:
    return RecurringPaymentDetailOut(
        **payment_out(view, today=today, remind_days_before=remind_days_before).model_dump(),
        occurrences=[occurrence_out(v, today=today, remind_days_before=remind_days_before) for v in occurrences],
    )
