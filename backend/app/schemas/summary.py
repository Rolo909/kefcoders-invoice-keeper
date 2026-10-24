from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Currency


class SummaryPeriod(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date


class CurrencyTotalOut(BaseModel):
    currency: Currency
    planned: Decimal = Field(description="Все сроки периода, включая ещё не созданные плановые")
    paid: Decimal = Field(description="Оплачено на дату as_of")
    unpaid: Decimal = Field(description="planned − paid")
    overdue: Decimal = Field(description="Не оплачено на дату as_of, срок уже прошёл")
    paid_late: Decimal = Field(description="Оплачено позже срока")
    count_total: int
    count_paid: int
    count_overdue: int
    budget: Decimal | None = Field(description="Бюджет валюты, если запрошен целый месяц или год")
    budget_left: Decimal | None = Field(description="budget − planned")


class SummaryOut(BaseModel):
    period: SummaryPeriod
    as_of: date
    totals: list[CurrencyTotalOut] = Field(description="Всегда все три валюты: RUB, USD, EUR")
