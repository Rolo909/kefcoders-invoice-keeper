"""Тестовые данные для демонстрации (ARCHITECTURE.md §12) — те же, что в имитации API веб-панели.

Расходы хостинг-провайдера (как у aeza.ru): ЦОД и электроэнергия, каналы связи, IPv4-адреса,
колокация в Европе, лицензии панелей управления, офис и бухгалтерия.

Даты считаются от «сегодня», поэтому сценарий защиты работает в любой день:
аренда офиса в рублях со сроком через 2 дня (напоминание уходит сразу), канал связи в долларах
с просрочкой, стойка в Амстердаме в евро на 31-е число, оплаченная с опозданием, и т. д.

Запуск при старте контейнера: `python -m app.seed` (только если SEED_DEMO_DATA=true).
Выполняется один раз: маркер — пользователь anna.
"""

import asyncio
import calendar
import logging
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
from app.logging_setup import configure_logging
from app.models import Budget, PaymentOccurrence, RecurringPayment, User
from app.security import hash_password
from app.services import audit
from app.services.audit import AuditAction
from app.services.auth import find_user_by_login
from app.services.occurrences import ensure_occurrences

logger = logging.getLogger(__name__)

MARKER_LOGIN = "anna"
DEMO_USERS = (
    # логин, пароль, ФИО, почта, напоминания на почту
    # Почта в зоне .test — такие адреса не существуют, письма из демо никуда не уйдут.
    ("anna", "anna12345", "Анна Ковалёва", "anna@aeza.test", True),
    ("maria", "maria12345", "Мария Лебедева", "maria@aeza.test", False),
    ("user", "user12345", "Дмитрий Орлов", None, False),
)
BUDGETS = {  # валюта: (на месяц, на год)
    Currency.RUB: (Decimal("1100000"), Decimal("13000000")),
    Currency.USD: (Decimal("6000"), Decimal("70000")),
    Currency.EUR: (Decimal("7000"), Decimal("80000")),
}
_MONTHS = {Period.MONTHLY: 1, Period.QUARTERLY: 3, Period.YEARLY: 12}

PaidRule = Callable[[int, date], tuple[date, User] | None]


@dataclass(frozen=True)
class Spec:
    name: str
    description: str
    amount: str
    currency: Currency
    period: Period
    first: date
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


def _specs(today: date, anna: User, maria: User) -> list[Spec]:
    def paid_shifted(shift: int, who: list[User], *, before: date | None = None) -> PaidRule:
        """Оплачено через `shift` дней после срока (отрицательный — заранее); только сроки раньше `before`."""

        def rule(seq: int, due: date) -> tuple[date, User] | None:
            paid_on = due + timedelta(days=shift)
            if paid_on > today or (before is not None and due >= before):
                return None
            return paid_on, who[seq % len(who)]

        return rule

    def amsterdam(seq: int, due: date) -> tuple[date, User] | None:
        if seq < 2:
            return paid_shifted(0, [maria])(seq, due)
        return paid_shifted(3, [maria])(seq, due) if seq == 2 else None  # оплачено с опозданием

    t = today
    days = timedelta
    return [
        Spec("Аренда офиса, Санкт-Петербург", "Офис поддержки и продаж. Договор № 14/2025, оплата до 26-го числа.",
             "290000.00", Currency.RUB, Period.MONTHLY, _back(t + days(2), Period.MONTHLY, 4),
             paid_shifted(-1, [anna, maria], before=t + days(2))),
        Spec("Бухгалтерское и налоговое сопровождение", "Аутсорсинговая бухгалтерия, ежемесячный акт.", "65000.00",
             Currency.RUB, Period.MONTHLY, _back(t + days(1), Period.MONTHLY, 4),
             paid_shifted(-1, [anna], before=t + days(1))),
        Spec("Электроэнергия, стойки в ЦОД", "Счёт по показаниям счётчиков, 12 стоек в Москве.", "410000.00",
             Currency.RUB, Period.MONTHLY, _back(t - days(4), Period.MONTHLY, 4), paid_shifted(-1, [maria, anna])),
        Spec("Яндекс 360 для бизнеса", "Корпоративная почта и диск, 45 сотрудников.", "18000.00",
             Currency.RUB, Period.MONTHLY, _back(t - days(23), Period.MONTHLY, 3), paid_shifted(0, [anna, maria])),
        Spec("Страхование оборудования", "Полис на серверное и сетевое оборудование в ЦОД.", "180000.00",
             Currency.RUB, Period.QUARTERLY, _back(t + days(38), Period.QUARTERLY, 2),
             paid_shifted(-2, [anna], before=t)),
        Spec("Домены aeza.ru и aeza.net", "Продление у регистратора.", "2900.00",
             Currency.RUB, Period.YEARLY, t + days(20)),
        Spec("IP-транзит, канал 10 Гбит/с", "Магистральный канал связи для ЦОД в Москве.", "2400.00",
             Currency.USD, Period.MONTHLY, _back(t - days(10), Period.MONTHLY, 3),
             paid_shifted(0, [maria], before=t - days(10))),
        Spec("Лицензии cPanel", "Панели управления для тарифов виртуального хостинга, 30 серверов.", "690.00",
             Currency.USD, Period.MONTHLY, _back(t - days(6), Period.MONTHLY, 3),
             paid_shifted(-1, [maria], before=t - days(6))),
        Spec("Мониторинг сети и серверов", "Внешняя проверка доступности узлов и оповещения дежурным.", "320.00",
             Currency.USD, Period.MONTHLY, _back(t - days(2), Period.MONTHLY, 3), paid_shifted(0, [maria])),
        Spec("Аренда блока IPv4-адресов /24", "256 адресов под новые выделенные серверы клиентов.", "1900.00",
             Currency.USD, Period.MONTHLY, t + days(4), created_on=t - days(1)),
        Spec("Колокация, Франкфурт", "Две стойки и кросс-подключения в европейском ЦОД.", "2900.00",
             Currency.EUR, Period.MONTHLY, _back(t - days(19), Period.MONTHLY, 3), paid_shifted(0, [anna])),
        Spec("Аренда стойки, Амстердам", "Оплата 31-го; в коротких месяцах — в последний день.", "3100.00",
             Currency.EUR, Period.MONTHLY, _latest_31st(t), amsterdam),
        Spec("Резервный канал связи", "Отключён после запуска второго канала 10 Гбит/с.", "85000.00",
             Currency.RUB, Period.MONTHLY, _back(t - days(75), Period.MONTHLY, 4), paid_shifted(0, [anna]),
             stopped_on=t - days(70)),
    ]  # fmt: skip


def _moment(day: date, hour: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=tz)


async def _create_users(session: AsyncSession, today: date, tz: ZoneInfo) -> dict[str, User]:
    users = {}
    for login, password, full_name, email, notify in DEMO_USERS:
        user = User(
            login=login,
            password_hash=hash_password(password),
            full_name=full_name,
            email=email,
            notify_email=notify,
            role=Role.USER,
            created_at=_moment(today - timedelta(days=140), 10, tz),
        )
        session.add(user)
        users[login] = user
    await session.flush()
    return users


async def _create_payment(session: AsyncSession, spec: Spec, admin: User, today: date, tz: ZoneInfo) -> None:
    payment = RecurringPayment(
        name=spec.name,
        description=spec.description,
        amount=Decimal(spec.amount),
        currency=spec.currency,
        period=spec.period,
        first_due_date=spec.first,
        created_by=admin.id,
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
        await ensure_occurrences(session, [payment], today=today, horizon_days=get_settings().occurrence_horizon_days)
    else:  # прекращённый платёж: история до даты прекращения
        seq = 0
        while (due := due_date(payment.first_due_date, payment.period, seq)) <= spec.stopped_on:
            session.add(
                PaymentOccurrence(
                    recurring_payment_id=payment.id,
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
        await _mark_paid(session, payment, spec.paid, tz)


async def _mark_paid(session: AsyncSession, payment: RecurringPayment, rule: PaidRule, tz: ZoneInfo) -> None:
    periods = await session.scalars(
        select(PaymentOccurrence).where(PaymentOccurrence.recurring_payment_id == payment.id)
    )
    for period in periods:
        mark = rule(period.seq, period.due_date)
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


def _budgets(today: date) -> list[Budget]:
    budgets = []
    for currency, (monthly, yearly) in BUDGETS.items():
        budgets.append(
            Budget(
                currency=currency,
                period_type=BudgetPeriodType.MONTH,
                year=today.year,
                month=today.month,
                amount=monthly,
            )
        )
        budgets.append(Budget(currency=currency, period_type=BudgetPeriodType.YEAR, year=today.year, amount=yearly))
    return budgets


async def seed_demo_data(session: AsyncSession, *, today: date, tz: ZoneInfo) -> bool:
    """Создаёт тестовые данные. False — данные уже есть (маркер найден) или нет администратора."""
    if await find_user_by_login(session, MARKER_LOGIN) is not None:
        return False
    admin = await session.scalar(select(User).where(User.is_system))
    if admin is None:
        logger.warning("Тестовые данные не созданы: нет администратора — сначала python -m app.bootstrap")
        return False

    users = await _create_users(session, today, tz)
    for spec in _specs(today, users["anna"], users["maria"]):
        await _create_payment(session, spec, admin, today, tz)
    session.add_all(_budgets(today))
    await session.flush()
    return True


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
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
