import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.enums import BudgetPeriodType, Currency
from app.models.base import MONEY_PRECISION, MONEY_SCALE, UuidPkMixin, pg_enum
from app.models.payment import CURRENCY_ENUM


class Budget(UuidPkMixin, Base):
    """Бюджет команды по валюте на месяц или на год."""

    __tablename__ = "budgets"
    __table_args__ = (
        # NULLS NOT DISTINCT: годовой бюджет (month IS NULL) тоже уникален.
        UniqueConstraint("team_id", "currency", "period_type", "year", "month", postgresql_nulls_not_distinct=True),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(period_type = 'month' AND month BETWEEN 1 AND 12) OR (period_type = 'year' AND month IS NULL)",
            name="month_matches_period_type",
        ),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM)
    period_type: Mapped[BudgetPeriodType] = mapped_column(pg_enum(BudgetPeriodType, "budget_period_type"))
    year: Mapped[int] = mapped_column(SmallInteger)
    month: Mapped[int | None] = mapped_column(SmallInteger)
    amount: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
