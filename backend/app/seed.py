"""Тестовые данные для демонстрации (TASK_PLAN §12, §18) — те же, что в имитации API веб-панели.

Даты считаются от «сегодня», поэтому сценарий защиты работает в любой день:
аренда в рублях со сроком через 2 дня (напоминание уходит сразу), сервер в долларах с просрочкой,
подписка в евро на 31-е число, оплаченная с опозданием, и т. д.

Две команды: Kefcoders (anna, maria, user) и Студия дизайна (oleg), у каждой свои платежи и бюджеты,
плюс два общих платежа — каждая команда оплачивает их сама. Студия создана позже общих платежей,
поэтому у неё нет «долгов» за сроки до своего появления.

Запуск при старте контейнера: `python -m app.seed` (только если SEED_DEMO_DATA=true).
Выполняется один раз: маркер — пользователь anna.
"""

import asyncio
import calendar
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import engine, session_factory
from app.domain.enums import BudgetPeriodType, Currency, OccurrenceStatus, Period, Role
from app.domain.schedule import add_months_clamped, due_date
from app.domain.status import today_in
from app.models import Budget, PaymentOccurrence, RecurringPayment, Team, User
from app.security import hash_password
from app.services import audit
from app.services.audit import AuditAction
from app.services.auth import find_user_by_login
from app.services.occurrences import ensure_occurrences

logger = logging.getLogger(__name__)

MARKER_LOGIN = "anna"
KEF, STUDIO = "Kefcoders", "Студия дизайна"
# Команда: сколько дней назад создана. Telegram-чат не задан — напоминания идут в TELEGRAM_CHAT_ID из .env.
DEMO_TEAMS = {KEF: 240, STUDIO: 100}
DEMO_USERS = (
    # логин, пароль, ФИО, почта, напоминания на почту, команда, создан дней назад
    ("anna", "anna12345", "Анна Ковалёва", "anna@kefcoders.ru", True, KEF, 140),
    ("maria", "maria12345", "Мария Лебедева", "maria@kefcoders.ru", False, KEF, 140),
    ("user", "user12345", "Дмитрий Орлов", None, False, KEF, 100),
    ("oleg", "oleg12345", "Олег Смирнов", "oleg@studio.ru", False, STUDIO, 99),
)
BUDGETS = {  # команда: {валюта: (на месяц, на год)}
    KEF: {
        Currency.RUB: (Decimal("90000"), Decimal("1100000")),
        Currency.USD: (Decimal("250"), Decimal("3000")),
        Currency.EUR: (Decimal("60"), Decimal("700")),
    },
    STUDIO: {
        Currency.RUB: (Decimal("70000"), Decimal("800000")),
        Currency.USD: (Decimal("40"), Decimal("450")),
        Currency.EUR: (Decimal("100"), Decimal("1200")),
    },
}
_MONTHS = {Period.MONTHLY: 1, Period.QUARTERLY: 3, Period.YEARLY: 12}

# (номер периода, срок, команда периода) → (дата оплаты, кто оплатил) или None — не оплачено.
PaidRule = Callable[[int, date, str], tuple[date, User] | None]


@dataclass(frozen=True)
class Spec:
    name: str
    description: str
    amount: str
    currency: Currency
    period: Period
    first: date
    team: str | None  # None — общий платёж: период у каждой команды
    paid: PaidRule | None = None
    stopped_on: date | None = None
    created_on: date | None = None


def _back(anchor: date, period: Period, periods: int) -> date:
    """Срок на `periods` периодов раньше якоря — с тем же правилом «нет числа → последний день»."""
    return add_months_clamped(anchor, -_MONTHS[period] * periods)


def _latest_31st(today: date) -> date:
    """31-е число не позже чем три месяца назад — чтобы показать правило «в коротких месяцах — последний день»."""
    year, month = today.year, today.month - 3
    while True:
        if month < 1:
            year, month = year - 1, month + 12
        if calendar.monthrange(year, month)[1] == 31:
            return date(year, month, 31)
        month -= 1


def _specs(today: date, users: dict[str, User]) -> list[Spec]:
    anna, maria, oleg = users["anna"], users["maria"], users["oleg"]
    crews = {KEF: [anna, maria], STUDIO: [oleg]}

    def paid_shifted(shift: int, who: list[User] | None = None, *, before: date | None = None) -> PaidRule:
        """Оплачено через `shift` дней после срока (отрицательный — заранее); только сроки раньше `before`.
        Без `who` платит участник команды периода — так у общего платежа каждая команда платит сама."""

        def rule(seq: int, due: date, team: str) -> tuple[date, User] | None:
            paid_on = due + timedelta(days=shift)
            if paid_on > today or (before is not None and due >= before):
                return None
            payers = who or crews[team]
            return paid_on, payers[seq % len(payers)]

        return rule

    def figma(seq: int, due: date, team: str) -> tuple[date, User] | None:
        if seq < 2:
            return paid_shifted(0, [maria])(seq, due, team)
        return paid_shifted(3, [maria])(seq, due, team) if seq == 2 else None  # оплачено с опозданием

    def accounting(seq: int, due: date, team: str) -> tuple[date, User] | None:
        # Студия не оплатила прошлый месяц — видно, что у команд отметки раздельные.
        if team == STUDIO and due >= today - timedelta(days=40):
            return None
        return paid_shifted(-1, before=today + timedelta(days=1))(seq, due, team)

    t = today
    days = timedelta
    return [
        Spec("Аренда офиса", "Офис на Пушкинской, 12. Договор № 14/2025, оплата до 26-го числа.", "50000.00",
             Currency.RUB, Period.MONTHLY, _back(t + days(2), Period.MONTHLY, 4), KEF,
             paid_shifted(-1, [anna, maria], before=t + days(2))),
        Spec("Бухгалтерское сопровождение", "ООО «Баланс-Сервис», ежемесячный счёт каждой команде.", "25000.00",
             Currency.RUB, Period.MONTHLY, _back(t + days(1), Period.MONTHLY, 4), None, accounting),
        Spec("МТС Бизнес, интернет", "Лицевой счёт 7712 0045 8810.", "3900.00",
             Currency.RUB, Period.MONTHLY, _back(t - days(4), Period.MONTHLY, 4), KEF,
             paid_shifted(-1, [maria, anna])),
        Spec("Яндекс 360 для бизнеса", "Почта и диск, каждая команда платит за свои места.", "2400.00",
             Currency.RUB, Period.MONTHLY, _back(t - days(23), Period.MONTHLY, 3), None, paid_shifted(0)),
        Spec("Страхование офиса", "Полис «Ингосстрах» № 0471-2026.", "38000.00",
             Currency.RUB, Period.QUARTERLY, _back(t + days(38), Period.QUARTERLY, 2), KEF,
             paid_shifted(-2, [anna], before=t)),
        Spec("Домен invoicekeeper.ru", "Продление у регистратора REG.RU.", "1500.00",
             Currency.RUB, Period.YEARLY, t + days(20), KEF),
        Spec("Сервер DigitalOcean", "Droplet 4 vCPU / 8 GB, продакшен.", "20.00",
             Currency.USD, Period.MONTHLY, _back(t - days(10), Period.MONTHLY, 3), KEF,
             paid_shifted(0, [maria], before=t - days(10))),
        Spec("Sentry Team", "Мониторинг ошибок, 50 тыс. событий.", "26.00",
             Currency.USD, Period.MONTHLY, _back(t - days(6), Period.MONTHLY, 3), KEF,
             paid_shifted(-1, [maria], before=t - days(6))),
        Spec("GitHub Team", "11 мест, организация kefcoders.", "44.00",
             Currency.USD, Period.MONTHLY, _back(t - days(2), Period.MONTHLY, 3), KEF, paid_shifted(0, [maria])),
        Spec("AWS", "S3 и CloudFront для файлов клиентов.", "134.20",
             Currency.USD, Period.MONTHLY, t + days(4), KEF, created_on=t - days(1)),
        Spec("JetBrains All Products", "Лицензия на команду, 3 места.", "28.90",
             Currency.EUR, Period.MONTHLY, _back(t - days(19), Period.MONTHLY, 3), KEF, paid_shifted(0, [anna])),
        Spec("Figma Professional", "Оплата 31-го; в коротких месяцах — в последний день.", "15.00",
             Currency.EUR, Period.MONTHLY, _latest_31st(t), KEF, figma),
        Spec("Хостинг Timeweb", "Старый сервер, переехали на DigitalOcean.", "1290.00",
             Currency.RUB, Period.MONTHLY, _back(t - days(75), Period.MONTHLY, 4), KEF, paid_shifted(0, [anna]),
             stopped_on=t - days(70)),
        Spec("Аренда студии", "Лофт на Садовой, 5. Договор № 7/2026.", "35000.00",
             Currency.RUB, Period.MONTHLY, _back(t + days(6), Period.MONTHLY, 2), STUDIO,
             paid_shifted(-2, before=t)),
        Spec("Adobe Creative Cloud", "Все приложения, 2 места.", "89.99",
             Currency.EUR, Period.MONTHLY, _back(t - days(2), Period.MONTHLY, 2), STUDIO,
             paid_shifted(0, before=t - days(2))),
        Spec("Shutterstock", "Фотобанк, 750 изображений в месяц.", "29.00",
             Currency.USD, Period.MONTHLY, _back(t + days(12), Period.MONTHLY, 2), STUDIO, paid_shifted(-1)),
    ]  # fmt: skip


def _moment(day: date, hour: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=tz)


async def _create_teams(session: AsyncSession, admin: User, today: date, tz: ZoneInfo) -> dict[str, Team]:
    teams = {}
    for name, days_ago in DEMO_TEAMS.items():
        team = Team(name=name, created_at=_moment(today - timedelta(days=days_ago), 10, tz))
        session.add(team)
        await session.flush()
        audit.record(
            session,
            AuditAction.TEAM_CREATE,
            actor=admin,
            entity=("team", team.id),
            details={"name": name},
            at=team.created_at,
        )
        teams[name] = team
    return teams


async def _create_users(session: AsyncSession, teams: dict[str, Team], today: date, tz: ZoneInfo) -> dict[str, User]:
    users = {}
    for login, password, full_name, email, notify, team, days_ago in DEMO_USERS:
        user = User(
            login=login,
            team_id=teams[team].id,
            password_hash=hash_password(password),
            full_name=full_name,
            email=email,
            notify_email=notify,
            role=Role.USER,
            created_at=_moment(today - timedelta(days=days_ago), 10, tz),
        )
        session.add(user)
        users[login] = user
    await session.flush()
    return users


async def _create_payment(
    session: AsyncSession, spec: Spec, admin: User, teams: dict[str, Team], today: date, tz: ZoneInfo
) -> None:
    team = None if spec.team is None else teams[spec.team]
    payment = RecurringPayment(
        name=spec.name,
        description=spec.description,
        amount=Decimal(spec.amount),
        currency=spec.currency,
        period=spec.period,
        first_due_date=spec.first,
        created_by=admin.id,
        team_id=None if team is None else team.id,
        created_at=_moment(spec.created_on or spec.first - timedelta(days=25), 11, tz),
    )
    session.add(payment)
    await session.flush()
    audit.record(
        session,
        AuditAction.PAYMENT_CREATE,
        actor=admin,
        entity=("recurring_payment", payment.id),
        details={"payment_name": payment.name, "amount": spec.amount, "currency": spec.currency.value},
        at=payment.created_at,
    )

    if spec.stopped_on is None:
        await ensure_occurrences(
            session, [payment], today=today, horizon_days=get_settings().occurrence_horizon_days, timezone=tz
        )
    else:  # прекращённый платёж команды: история до даты прекращения
        if team is None:
            raise ValueError("Прекращённый тестовый платёж должен быть командным")
        seq = 0
        while (due := due_date(payment.first_due_date, payment.period, seq)) <= spec.stopped_on:
            session.add(
                PaymentOccurrence(
                    recurring_payment_id=payment.id,
                    team_id=team.id,
                    seq=seq,
                    due_date=due,
                    amount=payment.amount,
                    currency=payment.currency,
                )
            )
            seq += 1
        payment.is_active = False
        payment.deleted_at = _moment(spec.stopped_on, 11, tz)
    await session.flush()

    if spec.paid is not None:
        names = {t.id: name for name, t in teams.items()}
        await _mark_paid(session, payment, spec.paid, names, tz)


async def _mark_paid(
    session: AsyncSession, payment: RecurringPayment, rule: PaidRule, team_names: dict[uuid.UUID, str], tz: ZoneInfo
) -> None:
    periods = await session.scalars(
        select(PaymentOccurrence).where(PaymentOccurrence.recurring_payment_id == payment.id)
    )
    for period in periods:
        mark = rule(period.seq, period.due_date, team_names[period.team_id])
        if mark is None:
            continue
        paid_on, who = mark
        period.status = OccurrenceStatus.PAID
        period.paid_date = paid_on
        period.paid_by = who.id
        period.paid_marked_at = _moment(paid_on, 13, tz)
        audit.record(
            session,
            AuditAction.OCCURRENCE_MARK_PAID,
            actor=who,
            entity=("occurrence", period.id),
            details={
                "payment_name": payment.name,
                "due_date": period.due_date.isoformat(),
                "paid_date": paid_on.isoformat(),
            },
            at=period.paid_marked_at,
        )


def _budgets(teams: dict[str, Team], today: date) -> list[Budget]:
    budgets = []
    for name, amounts in BUDGETS.items():
        budgets += _team_budgets(teams[name], amounts, today)
    return budgets


def _team_budgets(team: Team, amounts: dict[Currency, tuple[Decimal, Decimal]], today: date) -> list[Budget]:
    budgets = []
    for currency, (monthly, yearly) in amounts.items():
        budgets.append(
            Budget(
                team_id=team.id,
                currency=currency,
                period_type=BudgetPeriodType.MONTH,
                year=today.year,
                month=today.month,
                amount=monthly,
            )
        )
        budgets.append(
            Budget(
                team_id=team.id, currency=currency, period_type=BudgetPeriodType.YEAR, year=today.year, amount=yearly
            )
        )
    return budgets


async def seed_demo_data(session: AsyncSession, *, today: date, tz: ZoneInfo) -> bool:
    """Создаёт тестовые данные. False — данные уже есть (маркер найден) или нет администратора."""
    if await find_user_by_login(session, MARKER_LOGIN) is not None:
        return False
    admin = await session.scalar(select(User).where(User.is_system))
    if admin is None:
        logger.warning("Тестовые данные не созданы: нет администратора — сначала python -m app.bootstrap")
        return False

    teams = await _create_teams(session, admin, today, tz)
    users = await _create_users(session, teams, today, tz)
    for spec in _specs(today, users):
        await _create_payment(session, spec, admin, teams, today, tz)
    session.add_all(_budgets(teams, today))
    await session.flush()
    return True


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.seed_demo_data:
        logger.info("SEED_DEMO_DATA=false — тестовые данные не создаются")
        return
    try:
        async with session_factory() as session:
            created = await seed_demo_data(session, today=today_in(settings.timezone), tz=settings.timezone)
            await session.commit()
        logger.info("Тестовые данные созданы" if created else "Тестовые данные уже есть — пропускаю")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
