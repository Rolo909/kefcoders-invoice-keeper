import uuid
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import BudgetPeriodType, Currency
from app.schemas.payment import CENT, MAX_AMOUNT

MIN_YEAR = 2000
MAX_YEAR = 2100


class BudgetItem(BaseModel):
    """Бюджет валюты на месяц (month — номер месяца) или на год (month — null)."""

    model_config = ConfigDict(extra="forbid")

    team_id: uuid.UUID
    currency: Currency
    period_type: BudgetPeriodType
    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    month: int | None = Field(default=None, ge=1, le=12)
    amount: Decimal = Field(description="Строка с точкой, например «90000.00»")

    @field_validator("amount")
    @classmethod
    def _amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value >= MAX_AMOUNT or value != value.quantize(CENT):
            raise ValueError("Бюджет — сумма больше нуля, не больше двух знаков после запятой")
        return value.quantize(CENT)

    @model_validator(mode="after")
    def _month_matches_period(self) -> Self:
        if self.period_type is BudgetPeriodType.MONTH and self.month is None:
            raise ValueError("Для бюджета на месяц укажите month — номер месяца")
        if self.period_type is BudgetPeriodType.YEAR and self.month is not None:
            raise ValueError("У бюджета на год month должен быть пустым (null)")
        return self
