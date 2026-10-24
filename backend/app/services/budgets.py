"""Бюджеты по валютам на месяц и год — для итогов «план / бюджет / остаток»."""

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import BudgetPeriodType
from app.models import Budget, User
from app.schemas.budget import BudgetItem
from app.services import audit
from app.services.audit import AuditAction

_UNIQUE_KEY = "uq_budgets_currency_period_type_year_month"


async def list_budgets(session: AsyncSession, *, year: int, month: int) -> list[Budget]:
    """Годовые бюджеты года и месячные — выбранного месяца."""
    stmt = (
        select(Budget)
        .where(
            Budget.year == year,
            or_(
                Budget.period_type == BudgetPeriodType.YEAR,
                (Budget.period_type == BudgetPeriodType.MONTH) & (Budget.month == month),
            ),
        )
        .order_by(Budget.period_type, Budget.currency)
    )
    return list(await session.scalars(stmt))


async def save_budgets(session: AsyncSession, items: list[BudgetItem], *, actor: User, ip: str | None) -> list[Budget]:
    """Создать или обновить бюджеты одним запросом. Повтор одного бюджета в списке — берётся последний."""
    unique = {(i.currency, i.period_type, i.year, i.month): i for i in items}
    if not unique:
        return []
    stmt = pg_insert(Budget).values(
        [
            {"currency": i.currency, "period_type": i.period_type, "year": i.year, "month": i.month, "amount": i.amount}
            for i in unique.values()
        ]
    )
    saved = await session.scalars(
        stmt.on_conflict_do_update(constraint=_UNIQUE_KEY, set_={"amount": stmt.excluded.amount})
        .returning(Budget)
        .execution_options(populate_existing=True)
    )
    budgets = sorted(saved, key=lambda b: (b.period_type, b.currency))
    audit.record(session, AuditAction.BUDGET_UPDATE, actor=actor, details={"items": len(budgets)}, ip=ip)
    await session.commit()
    return budgets
