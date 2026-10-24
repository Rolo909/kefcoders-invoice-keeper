import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import Currency
from app.schemas.payment import OccurrenceOut
from app.schemas.team import TeamBrief


class PlannedItemOut(BaseModel):
    recurring_payment_id: uuid.UUID
    team: TeamBrief
    name: str
    due_date: date
    amount: Decimal
    currency: Currency


class CalendarDayOut(BaseModel):
    date: date
    occurrences: list[OccurrenceOut] = Field(description="Созданные периоды со сроком в этот день")
    planned: list[PlannedItemOut] = Field(description="Будущие сроки, для которых периоды ещё не созданы")


class CalendarMonthOut(BaseModel):
    month: str = Field(description="ГГГГ-ММ")
    days: list[CalendarDayOut] = Field(description="Только дни, в которые есть сроки, по возрастанию")
