import logging
import re
from email.message import EmailMessage
from html import unescape

import aiosmtplib
from sqlalchemy import select

from app.db import SessionFactory
from app.domain.enums import NotificationChannel, NotificationKind
from app.models import User
from app.services.notifiers.base import Reminder, SendResult, TeamTarget
from app.services.notifiers.formatting import format_date, format_money, reminder_text_html

SEND_TIMEOUT_SECONDS = 10
NO_RECIPIENTS = "Нет получателей: включите письма у пользователей или задайте EMAIL_EXTRA_RECIPIENTS"

logger = logging.getLogger(__name__)


def subject(reminder: Reminder) -> str:
    money = f"{format_money(reminder.amount)} {reminder.currency.value}"
    if reminder.kind is NotificationKind.OVERDUE:
        return f"Просрочена оплата «{reminder.payment_name}»: {money}"
    return f"Оплата «{reminder.payment_name}»: {money} до {format_date(reminder.due_date)}"


def _plain(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html))


class EmailNotifier:
    """Письмо с напоминанием всем пользователям, включившим письма, и адресам из EMAIL_EXTRA_RECIPIENTS.

    Получатели — в скрытой копии: друг другу адреса не видны.
    """

    channel = NotificationChannel.EMAIL

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        start_tls: bool = False,
        extra_recipients: list[str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._start_tls = start_tls
        self._extra = extra_recipients or []

    async def recipients(self, team: TeamTarget | None = None) -> list[str]:
        """Включившие письма участники команды (или все, если команда не указана) и адреса из .env."""
        conditions = [User.notify_email, User.email.is_not(None)]
        if team is not None:
            conditions.append(User.team_id == team.id)
        async with self._session_factory() as session:
            emails = await session.scalars(select(User.email).where(*conditions))
            found = [e for e in emails if e]
        return list(dict.fromkeys([*found, *self._extra]))

    async def send(self, reminder: Reminder) -> SendResult:
        html = reminder_text_html(reminder)
        return await self._send(reminder.team, subject(reminder), _plain(html), html.replace("\n", "<br>"))

    async def check(self, team: TeamTarget | None = None) -> SendResult:
        text = "Проверка связи: Invoice Keeper присылает на этот адрес напоминания об оплате."
        return await self._send(team, "Invoice Keeper: проверка почты", text, text)

    async def _send(self, team: TeamTarget | None, title: str, text: str, html: str) -> SendResult:
        recipients = await self.recipients(team)
        if not recipients:
            return SendResult(ok=False, error=NO_RECIPIENTS, attempted=False)
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = self._sender
        message["Subject"] = title
        message.set_content(text)
        message.add_alternative(f"<html><body style='font-family:sans-serif'>{html}</body></html>", subtype="html")
        try:
            await aiosmtplib.send(
                message,
                recipients=recipients,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                start_tls=self._start_tls,
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            logger.warning("Почта не отправлена: %s", exc)
            return SendResult(ok=False, error=f"Почтовый сервер недоступен: {exc.__class__.__name__}: {exc}")
        return SendResult(ok=True)
