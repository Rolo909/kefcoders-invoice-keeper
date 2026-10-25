"""Итоговые суммы по валютам — отдельно по каждой валюте, без конвертации (ARCHITECTURE.md §4.7)."""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import BudgetPeriodType, Currency, OccurrenceStatus
from app.models import Budget, PaymentOccurrence
from app.schemas.payment import CENT
from app.services.planning import planned_between

Occ = PaymentOccurrence
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CurrencyTotals:
    currency: Currency
    planned: Decimal
    paid: Decimal
    unpaid: Decimal
    overdue: Decimal
    paid_late: Decimal
    count_total: int
    count_paid: int
    count_overdue: int
    budget: Decimal | None
    budget_left: Decimal | None


def _budget_scope(start: date, end: date) -> tuple[BudgetPeriodType, int | None] | None:
    """Бюджет сравнивается только с целым календарным месяцем или годом."""
    if start.day == 1 and end == start.replace(day=calendar.monthrange(start.year, start.month)[1]):
        return BudgetPeriodType.MONTH, start.month
    if (start.month, start.day) == (1, 1) and end == date(start.year, 12, 31):
        return BudgetPeriodType.YEAR, None
    return None


async def _budgets(session: AsyncSession, start: date, end: date) -> dict[Currency, Decimal]:
    scope = _budget_scope(start, end)
    if scope is None:
        return {}
    period_type, month = scope
    month_condition = Budget.month.is_(None) if month is None else Budget.month == month
    rows = await session.execute(
        select(Budget.currency, Budget.amount).where(
            Budget.period_type == period_type, Budget.year == start.year, month_condition
        )
    )
    return {currency: amount for currency, amount in rows}


def _sum(condition: ColumnElement[bool] | None = None) -> ColumnElement[Decimal]:
    total = func.sum(Occ.amount) if condition is None else func.sum(Occ.amount).filter(condition)
    return func.coalesce(total, ZERO)


def _count(condition: ColumnElement[bool]) -> ColumnElement[int]:
    return func.count().filter(condition)


async def currency_totals(session: AsyncSession, *, start: date, end: date, as_of: date) -> list[CurrencyTotals]:
    """Итоги за [start, end] по срокам; «оплачено» и «просрочено» — по состоянию на дату as_of."""
    paid_as_of = and_(Occ.status == OccurrenceStatus.PAID, Occ.paid_date <= as_of)
    overdue = and_(not_(paid_as_of), Occ.due_date < as_of)
    paid_late = and_(paid_as_of, Occ.paid_date > Occ.due_date)
    rows = await session.execute(
        select(
            Occ.currency,
            _sum(),
            func.count(),
            _sum(paid_as_of),
            _count(paid_as_of),
            _sum(overdue),
            _count(overdue),
            _sum(paid_late),
        )
        .where(Occ.due_date.between(start, end))
        .group_by(Occ.currency)
    )
    created = {row[0]: row[1:] for row in rows}

    planned_sum: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    planned_count: dict[Currency, int] = defaultdict(int)
    for item in await planned_between(session, start, end):
        planned_sum[item.payment.currency] += item.payment.amount
        planned_count[item.payment.currency] += 1

    budgets = await _budgets(session, start, end)
    totals = []
    for currency in Currency:
        total, count, paid, count_paid, overdue_sum, count_overdue, late = created.get(
            currency, (ZERO, 0, ZERO, 0, ZERO, 0, ZERO)
        )
        planned = total + planned_sum[currency]
        budget = budgets.get(currency)
        totals.append(
            CurrencyTotals(
                currency=currency,
                planned=planned.quantize(CENT),
                paid=paid.quantize(CENT),
                unpaid=(planned - paid).quantize(CENT),
                overdue=overdue_sum.quantize(CENT),
                paid_late=late.quantize(CENT),
                count_total=count + planned_count[currency],
                count_paid=count_paid,
                count_overdue=count_overdue,
                budget=budget,
                budget_left=None if budget is None else (budget - planned).quantize(CENT),
            )
        )
    return totals
