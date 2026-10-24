"""Telegram: привязка аккаунта по одноразовому коду и отметка оплаты кнопкой «Оплачено» в напоминании.

Кнопку может нажать любой участник чата, поэтому оплату отмечает только тот, чей Telegram
привязан к учётной записи панели — так в истории видно, кто именно оплатил.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Final

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OccurrenceStatus
from app.models import PaymentOccurrence, RecurringPayment, TelegramLinkCode, User
from app.services import audit
from app.services.audit import AuditAction

LINK_CODE_TTL: Final = timedelta(minutes=10)
LINK_CODE_DIGITS: Final = 6
PAY_CALLBACK_PREFIX: Final = "pay:"


# ---------- привязка аккаунта ----------


def _new_code() -> str:
    return f"{secrets.randbelow(10**LINK_CODE_DIGITS):0{LINK_CODE_DIGITS}d}"


async def create_link_code(session: AsyncSession, user: User, *, now: datetime) -> TelegramLinkCode:
    """Новый одноразовый код; прежние неиспользованные коды пользователя перестают действовать."""
    await session.execute(
        delete(TelegramLinkCode).where(TelegramLinkCode.user_id == user.id, TelegramLinkCode.used_at.is_(None))
    )
    while True:
        link = TelegramLinkCode(code=_new_code(), user_id=user.id, expires_at=now + LINK_CODE_TTL)
        try:
            async with session.begin_nested():  # совпадение кода с чужим действующим — выбрать другой
                session.add(link)
        except IntegrityError:
            continue
        await session.commit()
        return link


class LinkResult(StrEnum):
    LINKED = "linked"
    INVALID_CODE = "invalid_code"


@dataclass(frozen=True)
class LinkOutcome:
    result: LinkResult
    user: User | None = None


async def link_account(session: AsyncSession, code: str, *, telegram_user_id: int, now: datetime) -> LinkOutcome:
    """Привязать Telegram к учётной записи по коду из панели. Один Telegram — одна учётная запись."""
    link = await session.scalar(
        select(TelegramLinkCode)
        .where(
            TelegramLinkCode.code == code.strip(),
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > now,
        )
        .with_for_update()
    )
    if link is None:
        return LinkOutcome(LinkResult.INVALID_CODE)
    # Этот Telegram был привязан к другому пользователю — привязка переходит к новому.
    await session.execute(
        update(User)
        .where(User.telegram_user_id == telegram_user_id, User.id != link.user_id)
        .values(telegram_user_id=None)
    )
    user = await session.get(User, link.user_id)
    if user is None:  # пользователя удалили, пока код был действителен
        return LinkOutcome(LinkResult.INVALID_CODE)
    user.telegram_user_id = telegram_user_id
    link.used_at = now
    await session.commit()
    return LinkOutcome(LinkResult.LINKED, user)


# ---------- кнопка «Оплачено» ----------


def pay_callback_data(occurrence_id: uuid.UUID) -> str:
    return f"{PAY_CALLBACK_PREFIX}{occurrence_id}"


def parse_pay_callback(data: str | None) -> uuid.UUID | None:
    if not data or not data.startswith(PAY_CALLBACK_PREFIX):
        return None
    try:
        return uuid.UUID(data.removeprefix(PAY_CALLBACK_PREFIX))
    except ValueError:
        return None


class PayResult(StrEnum):
    PAID = "paid"
    ALREADY_PAID = "already_paid"
    NOT_LINKED = "not_linked"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class PayOutcome:
    result: PayResult
    user: User | None = None
    paid_date: date | None = None


async def mark_paid_from_telegram(
    session: AsyncSession,
    occurrence_id: uuid.UUID,
    *,
    telegram_user_id: int,
    today: date,
    now: datetime,
) -> PayOutcome:
    """Отметить период оплаченным сегодняшним числом. Повторное нажатие дату не меняет."""
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return PayOutcome(PayResult.NOT_LINKED)
    row = (
        await session.execute(
            select(PaymentOccurrence, RecurringPayment)
            .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
            .where(PaymentOccurrence.id == occurrence_id)
            .with_for_update(of=PaymentOccurrence)
        )
    ).first()
    if row is None:
        return PayOutcome(PayResult.NOT_FOUND, user)
    occurrence, payment = row
    if occurrence.status is OccurrenceStatus.PAID:
        return PayOutcome(PayResult.ALREADY_PAID, user, occurrence.paid_date)

    occurrence.status = OccurrenceStatus.PAID
    occurrence.paid_date = today
    occurrence.paid_by = user.id
    occurrence.paid_marked_at = now
    audit.record(
        session,
        AuditAction.TELEGRAM_MARK_PAID,
        actor=user,
        entity=("occurrence", occurrence.id),
        details={
            "payment_name": payment.name,
            "due_date": occurrence.due_date.isoformat(),
            "paid_date": today.isoformat(),
        },
    )
    await session.commit()
    return PayOutcome(PayResult.PAID, user, today)
