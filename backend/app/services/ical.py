"""Подписка на календарь: сроки платежей в формате iCalendar (RFC 5545) для Google, Outlook и Яндекс-календаря.

Календарные сервисы не умеют входить в панель, поэтому ссылка содержит секрет пользователя
(users.calendar_token). Сервис периодически перечитывает файл целиком — так оплата, отмена
отметки или новый платёж появляются в календаре сами. У каждого срока постоянный UID
(платёж и номер периода), поэтому плановый срок и созданный позже период — одно и то же событие.
"""

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Currency, OccurrenceState
from app.domain.status import days_overdue, occurrence_state
from app.models import User
from app.services import audit
from app.services.audit import AuditAction
from app.services.notifiers.formatting import format_date, format_money, plural_days
from app.services.occurrences import OccurrenceView
from app.services.planning import PlannedDue

CALENDAR_NAME = "Invoice Keeper — платежи"
# Сколько истории и сколько будущего отдавать в календарь.
PAST_DAYS = 180
FUTURE_DAYS = 365
CURRENCY_SIGN = {Currency.RUB: "₽", Currency.USD: "$", Currency.EUR: "€"}
LINE_LIMIT = 75  # байт в строке; длинные строки переносятся по RFC 5545, 3.1


# ---------- ссылка подписки ----------


async def issue_token(session: AsyncSession, user: User, *, ip: str | None) -> str:
    """Секрет ссылки пользователя: прежний, если уже выдан, иначе новый."""
    if user.calendar_token:
        return user.calendar_token
    user.calendar_token = secrets.token_urlsafe(32)
    audit.record(session, AuditAction.CALENDAR_LINK_CREATE, actor=user, entity=("user", user.id), ip=ip)
    await session.commit()
    return user.calendar_token


async def revoke_token(session: AsyncSession, user: User, *, ip: str | None) -> None:
    """Отключить ссылку: календари, подписанные на неё, перестанут получать сроки."""
    if user.calendar_token is None:
        return
    user.calendar_token = None
    audit.record(session, AuditAction.CALENDAR_LINK_REVOKE, actor=user, entity=("user", user.id), ip=ip)
    await session.commit()


async def user_by_token(session: AsyncSession, token: str) -> User | None:
    if not token:
        return None
    return await session.scalar(select(User).where(User.calendar_token == token))


# ---------- формат iCalendar ----------


def escape_text(value: str) -> str:
    """Экранирование TEXT по RFC 5545, 3.3.11."""
    return (
        value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Перенос строки длиннее 75 байт: продолжение начинается с пробела (RFC 5545, 3.1).
    Режем по символам, а не по байтам, — иначе разорвали бы кириллицу посреди UTF-8."""
    if len(line.encode()) <= LINE_LIMIT:
        return line
    parts: list[str] = []
    current, size, limit = "", 0, LINE_LIMIT
    for char in line:
        width = len(char.encode())
        if size + width > limit:
            parts.append(current)
            current, size, limit = "", 0, LINE_LIMIT - 1  # минус пробел в начале продолжения
        current += char
        size += width
    parts.append(current)
    return "\r\n ".join(parts)


def _money(amount: Decimal, currency: Currency) -> str:
    return f"{format_money(amount)} {CURRENCY_SIGN[currency]}"


def _ical_date(day: date) -> str:
    return day.strftime("%Y%m%d")


@dataclass(frozen=True)
class FeedEvent:
    uid: str
    due: date
    summary: str
    description: str
    url: str | None
    alarm_days: int | None  # за сколько дней напомнить; None — без напоминания (оплачено, прошло)


def occurrence_event(view: OccurrenceView, *, today: date, remind_days_before: int, panel_url: str | None) -> FeedEvent:
    occurrence, payment = view.occurrence, view.payment
    money = _money(occurrence.amount, occurrence.currency)
    state = occurrence_state(occurrence, today, remind_days_before)
    if state in (OccurrenceState.PAID, OccurrenceState.PAID_LATE) and occurrence.paid_date is not None:
        payer = (view.paid_by.full_name or view.paid_by.login) if view.paid_by else None
        late = " с опозданием" if state is OccurrenceState.PAID_LATE else ""
        summary = f"✅ Оплачено: {payment.name} — {money}"
        status = f"оплачено{late} {format_date(occurrence.paid_date)}" + (f" ({payer})" if payer else "")
    elif state is OccurrenceState.OVERDUE:
        summary = f"⚠️ Просрочено: {payment.name} — {money}"
        status = f"не оплачено, просрочено на {plural_days(days_overdue(occurrence, today))}"
    else:
        summary = f"💳 {payment.name} — {money}"
        status = "к оплате"
    lines = [f"Сумма: {money}", f"Срок оплаты: {format_date(occurrence.due_date)}", f"Статус: {status}"]
    if payment.deleted_at is not None:
        lines.append("Платёж прекращён — новых сроков не будет")
    url = f"{panel_url}/occurrences/{occurrence.id}" if panel_url else None
    if url:
        lines.append(f"Открыть в панели: {url}")
    unpaid_ahead = occurrence.paid_date is None and occurrence.due_date >= today
    return FeedEvent(
        uid=f"{payment.id}-{occurrence.seq}@invoice-keeper",
        due=occurrence.due_date,
        summary=summary,
        description="\n".join(lines),
        url=url,
        alarm_days=remind_days_before if unpaid_ahead else None,
    )


def planned_event(item: PlannedDue, *, remind_days_before: int, panel_url: str | None) -> FeedEvent:
    """Срок дальше горизонта созданных периодов: появится как период, когда подойдёт время."""
    payment = item.payment
    money = _money(payment.amount, payment.currency)
    lines = [f"Сумма: {money}", f"Срок оплаты: {format_date(item.due_date)}", "Статус: к оплате"]
    url = f"{panel_url}/recurring-payments/{payment.id}" if panel_url else None
    if url:
        lines.append(f"Открыть в панели: {url}")
    return FeedEvent(
        uid=f"{payment.id}-{item.seq}@invoice-keeper",
        due=item.due_date,
        summary=f"💳 {payment.name} — {money}",
        description="\n".join(lines),
        url=url,
        alarm_days=remind_days_before,
    )


def render_calendar(events: list[FeedEvent], *, now: datetime, timezone: str) -> str:
    """Готовый файл .ics: строки через CRLF, длинные строки перенесены."""
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Invoice Keeper//Payments//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(CALENDAR_NAME)}",
        f"X-WR-CALDESC:{escape_text('Сроки регулярных платежей: к оплате, оплачено, просрочено')}",
        f"X-WR-TIMEZONE:{timezone}",
        # Как часто календарю перечитывать ссылку (Google решает сам, остальные следуют подсказке).
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for event in sorted(events, key=lambda e: (e.due, e.uid)):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{_ical_date(event.due)}",
            f"DTEND;VALUE=DATE:{_ical_date(event.due + timedelta(days=1))}",
            f"SUMMARY:{escape_text(event.summary)}",
            f"DESCRIPTION:{escape_text(event.description)}",
            *([f"URL:{event.url}"] if event.url else []),
            "CATEGORIES:Платежи",
            "TRANSP:TRANSPARENT",  # не занимает время в расписании
        ]
        if event.alarm_days is not None:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"TRIGGER:-P{event.alarm_days}D",
                f"DESCRIPTION:{escape_text(event.summary)}",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
