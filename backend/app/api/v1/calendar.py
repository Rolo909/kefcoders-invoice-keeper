import calendar as month_calendar
import re
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import SettingsDep, TeamScopeDep, TodayDep
from app.api.v1.presenters import occurrence_out
from app.db import SessionDep
from app.errors import AppError
from app.schemas.calendar import CalendarDayOut, CalendarMonthOut, PlannedItemOut
from app.schemas.payment import OccurrenceOut
from app.schemas.team import TeamBrief
from app.services.occurrences import ensure_occurrences, views_between
from app.services.planning import planned_between

router = APIRouter(prefix="/payments", tags=["payments"])

MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _month_range(month: str) -> tuple[date, date]:
    match = MONTH_PATTERN.fullmatch(month)
    if match is None:
        raise AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "Месяц — в формате ГГГГ-ММ")
    year, number = int(match[1]), int(match[2])
    return date(year, number, 1), date(year, number, month_calendar.monthrange(year, number)[1])


@router.get(
    "/calendar",
    response_model=CalendarMonthOut,
    summary="Календарь оплат на месяц: сроки по дням, включая плановые",
)
async def calendar(
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    scope: TeamScopeDep,
    month: Annotated[str | None, Query(description="ГГГГ-ММ; по умолчанию — текущий месяц")] = None,
) -> CalendarMonthOut:
    label = month or today.strftime("%Y-%m")
    start, end = _month_range(label)
    await ensure_occurrences(session, today=today, horizon_days=settings.occurrence_horizon_days)
    await session.commit()

    occurrences: dict[date, list[OccurrenceOut]] = defaultdict(list)
    for view in await views_between(session, start, end, scope):
        out = occurrence_out(view, today=today, remind_days_before=settings.remind_days_before)
        occurrences[out.due_date].append(out)
    planned: dict[date, list[PlannedItemOut]] = defaultdict(list)
    for item in sorted(
        await planned_between(session, start, end, scope),
        key=lambda i: (i.due_date, i.payment.name, i.team.name.lower()),
    ):
        planned[item.due_date].append(
            PlannedItemOut(
                recurring_payment_id=item.payment.id,
                team=TeamBrief.model_validate(item.team),
                name=item.payment.name,
                due_date=item.due_date,
                amount=item.payment.amount,
                currency=item.payment.currency,
            )
        )

    days = [
        CalendarDayOut(date=day, occurrences=occurrences.get(day, []), planned=planned.get(day, []))
        for day in sorted(occurrences.keys() | planned.keys())
    ]
    return CalendarMonthOut(month=label, days=days)
