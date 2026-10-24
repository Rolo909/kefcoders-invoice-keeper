import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.enums import Currency, OccurrenceStatus, Period
from app.models.base import MONEY_PRECISION, MONEY_SCALE, CreatedAtMixin, UuidPkMixin, pg_enum

CURRENCY_ENUM = pg_enum(Currency, "currency")


class RecurringPayment(UuidPkMixin, CreatedAtMixin, Base):
    __tablename__ = "recurring_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("end_date IS NULL OR end_date >= first_due_date", name="end_after_first_due"),
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
    currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM)
    period: Mapped[Period] = mapped_column(pg_enum(Period, "payment_period"))
    first_due_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Платёж одной команды; null — общий: периоды создаются у каждой команды, каждая платит за себя.
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)


class PaymentOccurrence(UuidPkMixin, CreatedAtMixin, Base):
    """Период регулярного платежа: свой срок, своя отметка об оплате и фактическая дата."""

    __tablename__ = "payment_occurrences"
    __table_args__ = (
        # У общего платежа период с тем же seq есть у каждой команды.
        UniqueConstraint("recurring_payment_id", "team_id", "seq"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        CheckConstraint("amount > 0", name="amount_positive"),
        # Оплачено ⇔ указана фактическая дата; при отмене оплаты дата очищается.
        CheckConstraint("(status = 'paid') = (paid_date IS NOT NULL)", name="paid_date_matches_status"),
        Index("ix_payment_occurrences_status_due_date", "status", "due_date"),
        Index("ix_payment_occurrences_payment_due_date", "recurring_payment_id", "due_date"),
        Index("ix_payment_occurrences_team_due_date", "team_id", "due_date"),
    )

    recurring_payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recurring_payments.id", ondelete="CASCADE"))
    # Команда, которая платит этот период. Удалить можно только команду без оплат — её периоды уходят с ней.
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    # Копия суммы и валюты на момент создания периода: история не меняется задним числом.
    amount: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
    currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM)
    status: Mapped[OccurrenceStatus] = mapped_column(
        pg_enum(OccurrenceStatus, "occurrence_status"),
        default=OccurrenceStatus.UNPAID,
        server_default=OccurrenceStatus.UNPAID.value,
    )
    paid_date: Mapped[date | None] = mapped_column(Date)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    paid_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
