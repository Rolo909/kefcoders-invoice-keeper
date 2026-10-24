"""Telegram: привязка аккаунта по одноразовому коду и отметка оплаты кнопкой «Оплачено» в напоминании.

Кнопку может нажать любой участник чата, поэтому оплату отмечает только тот, чей Telegram
привязан к учётной записи панели и кто состоит в команде этого периода (или администратор), —
и только в чате этой команды. Так посторонний в чате или участник другой команды оплатить не может,
а в истории видно, кто именно оплатил.
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

from app.domain.enums import OccurrenceStatus, Role
from app.models import PaymentOccurrence, RecurringPayment, Team, TelegramLinkCode, User
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
    WRONG_CHAT = "wrong_chat"  # нажали не в чате команды периода
    NOT_MEMBER = "not_member"  # нажал не участник команды периода


@dataclass(frozen=True)
class PayOutcome:
    result: PayResult
    user: User | None = None  # кто нажал кнопку
    paid_date: date | None = None
    paid_by: User | None = None  # кто на самом деле отметил оплату (для «Уже оплачено»)
    team_name: str | None = None


@dataclass(frozen=True)
class PressedIn:
    """Чат, в котором нажали кнопку: id и, у публичных групп и каналов, @имя."""

    chat_id: int
    username: str | None = None


def is_team_chat(configured: str | None, pressed: PressedIn | None) -> bool:
    """Нажали в чате команды. В настройке — id чата (-100…) или @имя публичной группы."""
    if configured is None or pressed is None:
        return False
    if configured.startswith("@"):
        return pressed.username is not None and configured[1:].lower() == pressed.username.lower()
    return configured == str(pressed.chat_id)


def team_chat(team: Team, fallback_chat_id: str | None) -> str | None:
    """Куда уходят напоминания команды: её чат, а если он не задан — общий TELEGRAM_CHAT_ID."""
    return team.telegram_chat_id or fallback_chat_id


async def mark_paid_from_telegram(
    session: AsyncSession,
    occurrence_id: uuid.UUID,
    *,
    telegram_user_id: int,
    pressed_in: PressedIn | None,
    fallback_chat_id: str | None,
    today: date,
    now: datetime,
) -> PayOutcome:
    """Отметить период оплаченным сегодняшним числом. Повторное нажатие дату не меняет.

    Проверки по порядку: период есть → Telegram привязан → нажали в чате команды периода →
    нажал участник этой команды или администратор → период ещё не оплачен. Период заблокирован
    (FOR UPDATE), поэтому одновременные нажатия отмечают оплату один раз.
    """
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return PayOutcome(PayResult.NOT_LINKED)
    row = (
        await session.execute(
            select(PaymentOccurrence, RecurringPayment, Team)
            .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
            .join(Team, Team.id == PaymentOccurrence.team_id)
            .where(PaymentOccurrence.id == occurrence_id)
            .with_for_update(of=PaymentOccurrence)
        )
    ).first()
    if row is None:
        return PayOutcome(PayResult.NOT_FOUND, user)
    occurrence, payment, team = row
    if not is_team_chat(team_chat(team, fallback_chat_id), pressed_in):
        # Старое сообщение после смены чата или чужой чат: оплачивать нужно там, куда пришло напоминание.
        return PayOutcome(PayResult.WRONG_CHAT, user, team_name=team.name)
    if user.role is not Role.ADMIN and user.team_id != team.id:
        return PayOutcome(PayResult.NOT_MEMBER, user, team_name=team.name)
    if occurrence.status is OccurrenceStatus.PAID:
        # Кто-то уже оплатил (в том числе одновременно с вами) — дату и автора не трогаем.
        payer = await session.get(User, occurrence.paid_by) if occurrence.paid_by else None
        return PayOutcome(PayResult.ALREADY_PAID, user, occurrence.paid_date, payer, team.name)

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
            "team_name": team.name,
        },
    )
    await session.commit()
    return PayOutcome(PayResult.PAID, user, today, user, team.name)


# ---------- группа стала супергруппой ----------


async def migrate_team_chats(session: AsyncSession, old_chat_id: int, new_chat_id: int) -> list[Team]:
    """У супергруппы новый id: переносим его в команды, иначе напоминания перестанут доходить."""
    teams = list(await session.scalars(select(Team).where(Team.telegram_chat_id == str(old_chat_id))))
    for team in teams:
        team.telegram_chat_id = str(new_chat_id)
        audit.record(
            session,
            AuditAction.TEAM_UPDATE,
            actor=None,
            actor_login="telegram",
            entity=("team", team.id),
            details={"name": team.name, "telegram_chat_id": team.telegram_chat_id, "reason": "chat_migrated"},
        )
    await session.commit()
    return teams
