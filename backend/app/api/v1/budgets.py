from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import AdminUser, TeamScopeDep, TodayDep, client_ip
from app.db import SessionDep
from app.schemas.budget import MAX_YEAR, MIN_YEAR, BudgetItem
from app.services import budgets as budgets_service

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetItem], summary="Бюджеты на месяц и на год по валютам")
async def list_budgets(
    session: SessionDep,
    today: TodayDep,
    scope: TeamScopeDep,
    year: Annotated[int | None, Query(ge=MIN_YEAR, le=MAX_YEAR, description="По умолчанию — текущий год")] = None,
    month: Annotated[int | None, Query(ge=1, le=12, description="По умолчанию — текущий месяц")] = None,
) -> list[BudgetItem]:
    budgets = await budgets_service.list_budgets(
        session, year=year or today.year, month=month or today.month, scope=scope
    )
    return [BudgetItem.model_validate(b, from_attributes=True) for b in budgets]


@router.put(
    "",
    response_model=list[BudgetItem],
    summary="Задать бюджеты (только администратор)",
    description="Передайте список бюджетов: существующие обновляются, новые создаются.",
)
async def save_budgets(
    body: list[BudgetItem], admin: AdminUser, request: Request, session: SessionDep
) -> list[BudgetItem]:
    saved = await budgets_service.save_budgets(session, body, actor=admin, ip=client_ip(request))
    return [BudgetItem.model_validate(b, from_attributes=True) for b in saved]
