import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    Currency,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    OccurrenceState,
    OccurrenceStatus,
    Period,
)
from app.models.base import MONEY_PRECISION, MONEY_SCALE
from app.schemas.user import UserBrief

NAME_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000
MAX_AMOUNT = Decimal(10) ** (MONEY_PRECISION - MONEY_SCALE)
CENT = Decimal("0.01")

AMOUNT_RULE = "Сумма — больше нуля, не больше двух знаков после запятой"


class PaymentBrief(BaseModel):
    id: uuid.UUID
    name: str
    period: Period
    is_deleted: bool


class OccurrenceOut(BaseModel):
    id: uuid.UUID
    recurring_payment_id: uuid.UUID
    recurring_payment: PaymentBrief
    seq: int
    due_date: date
    amount: Decimal
    currency: Currency
    status: OccurrenceStatus
    paid_date: date | None
    paid_by: UserBrief | None
    paid_marked_at: datetime | None
    note: str | None
    is_overdue: bool
    state: OccurrenceState
    days_overdue: int
    attachments_count: int
    last_reminder_at: datetime | None = Field(description="Когда ушло последнее напоминание в Telegram")


class AuditLogOut(BaseModel):
    id: uuid.UUID
    at: datetime
    actor: UserBrief | None
    actor_login: str
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    details: dict[str, Any]
    ip: str | None


class NotificationLogOut(BaseModel):
    id: uuid.UUID
    occurrence_id: uuid.UUID
    payment_name: str
    due_date: date
    channel: NotificationChannel
    kind: NotificationKind
    status: NotificationStatus
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime


class OccurrenceDetailOut(OccurrenceOut):
    history: list[AuditLogOut]
    reminders: list[NotificationLogOut]


class RecurringPaymentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    amount: Decimal
    currency: Currency
    period: Period
    first_due_date: date
    end_date: date | None
    is_active: bool
    deleted_at: datetime | None
    created_by: UserBrief
    created_at: datetime
    next_occurrence: OccurrenceOut | None


class RecurringPaymentDetailOut(RecurringPaymentOut):
    occurrences: list[OccurrenceOut]


class RecurringPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    amount: Decimal = Field(description="Строка с точкой, например «50000.00»")
    currency: Currency
    period: Period = Period.MONTHLY
    next_due_date: date = Field(description="Дата ближайшей оплаты — от неё считаются все следующие сроки")
    end_date: date | None = Field(default=None, description="Последняя дата, до которой повторяется платёж")

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = value.strip()
        if not 1 <= len(name) <= NAME_MAX_LENGTH:
            raise ValueError(f"Название — от 1 до {NAME_MAX_LENGTH} символов")
        return name

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        if len(text) > DESCRIPTION_MAX_LENGTH:
            raise ValueError(f"Описание — не длиннее {DESCRIPTION_MAX_LENGTH} символов")
        return text or None

    @field_validator("amount")
    @classmethod
    def _amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value >= MAX_AMOUNT or value != value.quantize(CENT):
            raise ValueError(AMOUNT_RULE)
        return value.quantize(CENT)

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end_date is not None and self.end_date < self.next_due_date:
            raise ValueError("Дата окончания — не раньше даты ближайшей оплаты")
        return self


class OccurrenceUpdate(BaseModel):
    """Срок, сумма и валюта периода фиксированы — менять можно только отметку и фактическую дату."""

    model_config = ConfigDict(extra="forbid")

    status: OccurrenceStatus | None = None
    paid_date: date | None = Field(default=None, description="Фактическая дата оплаты; без неё — сегодня")
