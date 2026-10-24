import calendar
from dataclasses import asdict
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import SettingsDep, TeamScopeDep, TodayDep
from app.db import SessionDep
from app.errors import AppError
from app.schemas.summary import CurrencyTotalOut, SummaryOut, SummaryPeriod
from app.services.occurrences import ensure_occurrences
from app.services.summary import currency_totals

router = APIRouter(prefix="/payments", tags=["payments"])

MAX_RANGE = timedelta(days=5 * 366)


def _invalid(detail: str) -> AppError:
    return AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", detail)


@router.get("/summary", response_model=SummaryOut, summary="Получение итоговых сумм платежей по валютам")
async def summary(
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
    scope: TeamScopeDep,
    date_from: Annotated[
        date | None, Query(description="Начало периода; по умолчанию — 1-е число текущего месяца")
    ] = None,
    date_to: Annotated[date | None, Query(description="Конец периода; по умолчанию — конец текущего месяца")] = None,
    as_of: Annotated[date | None, Query(description="Итоги на дату; по умолчанию — сегодня")] = None,
) -> SummaryOut:
    start = date_from or today.replace(day=1)
    end = date_to or today.replace(day=calendar.monthrange(today.year, today.month)[1])
    if start > end:
        raise _invalid("Неверный период: начало позже конца")
    if end - start > MAX_RANGE:
        raise _invalid("Неверный период: не длиннее 5 лет")

    await ensure_occurrences(session, today=today, horizon_days=settings.occurrence_horizon_days)
    await session.commit()
    on_date = as_of or today
    totals = await currency_totals(session, start=start, end=end, as_of=on_date, scope=scope)
    return SummaryOut(
        period=SummaryPeriod(from_=start, to=end),
        as_of=on_date,
        totals=[CurrencyTotalOut(**asdict(t)) for t in totals],
    )
