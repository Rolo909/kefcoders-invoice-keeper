import ipaddress
import logging
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.db import SessionFactory
from app.domain.enums import NotificationChannel, NotificationKind, OccurrenceStatus
from app.models import Notification, PaymentOccurrence, RecurringPayment, TelegramMessage, User
from app.services.notifiers.base import Reminder, SendResult, SentMessage
from app.services.notifiers.formatting import paid_text_html, reminder_text_html
from app.services.telegram import pay_callback_data

TELEGRAM_API = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10
NOT_CONFIGURED = "Telegram не настроен: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env"
NO_RECIPIENTS = "Некому отправить: TELEGRAM_CHAT_ID не задан, и никто не привязал Telegram в панели"
# Статусы getChatMember, при которых человек видит сообщения чата.
IN_CHAT = {"creator", "administrator", "member"}
CHECK_TEXT = "✅ Проверка связи: Invoice Keeper пишет в этот чат напоминания об оплате."

logger = logging.getLogger(__name__)


def public_panel_url(public_web_url: str | None) -> str | None:
    """Адрес панели для кнопки-ссылки. Telegram отклоняет ссылки на localhost и внутренние адреса."""
    if not public_web_url:
        return None
    parts = urlsplit(public_web_url)
    host = parts.hostname or ""
    if parts.scheme not in {"http", "https"} or not host or host == "localhost" or host.endswith(".local"):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass  # доменное имя
    return public_web_url.rstrip("/")


def reminder_keyboard(reminder: Reminder, panel_url: str | None) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = [
        [{"text": "✅ Оплачено", "callback_data": pay_callback_data(reminder.occurrence_id)}]
    ]
    if panel_url:
        rows.append([{"text": "Открыть в панели", "url": f"{panel_url}/occurrences/{reminder.occurrence_id}"}])
    return {"inline_keyboard": rows}


class TelegramNotifier:
    """Напоминание в общий Telegram-чат и в личку тем привязанным пользователям, кого в чате нет.

    Привязанные — те, кто прислал боту /link: только им бот может написать в личку. После оплаты
    (в панели или кнопкой) все сообщения напоминания заменяются на «оплачено» — см. sync().
    """

    channel = NotificationChannel.TELEGRAM

    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
        *,
        public_web_url: str | None = None,
        session_factory: SessionFactory | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._panel_url = public_panel_url(public_web_url)
        self._session_factory = session_factory  # без неё — только общий чат (лички и правка выключены)
        self._transport = transport

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=TELEGRAM_API, timeout=SEND_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            response = await client.post(f"/bot{self._token}/{method}", json=payload)
        body: dict[str, Any] = response.json()
        return body

    async def send(self, reminder: Reminder) -> SendResult:
        """Сначала общий чат, затем лички привязанным пользователям, которых в чате нет.

        Не дошло в общий чат — напоминание повторится целиком. Не дошло в чью-то личку (например,
        человек заблокировал бота) — это не мешает остальным и записывается в лог.
        """
        if not self._token:
            return SendResult(ok=False, error=NOT_CONFIGURED, attempted=False)
        content = {"text": reminder_text_html(reminder), "reply_markup": reminder_keyboard(reminder, self._panel_url)}
        sent: list[SentMessage] = []
        group_message_id: int | None = None
        if self._chat_id:
            result = await self._send_message(self._chat_id, content)
            if not result.ok:
                return result
            group_message_id = result.telegram_message_id
            sent += result.telegram_messages
        for user_id, telegram_id in await self._linked_users():
            if self._chat_id and (str(telegram_id) == self._chat_id or await self._in_group(telegram_id)):
                continue  # видит напоминание в общем чате
            dm = await self._send_message(str(telegram_id), content, user_id=user_id)
            if dm.ok:
                sent += dm.telegram_messages
            else:
                logger.info("Личное напоминание не доставлено пользователю %s: %s", user_id, dm.error)
        if not sent:
            return SendResult(ok=False, error=NO_RECIPIENTS, attempted=False)
        return SendResult(ok=True, telegram_message_id=group_message_id, telegram_messages=tuple(sent))

    async def check(self) -> SendResult:
        if not self._token or not self._chat_id:
            return SendResult(ok=False, error=NOT_CONFIGURED, attempted=False)
        return await self._send_message(self._chat_id, {"text": CHECK_TEXT})

    async def _linked_users(self) -> list[tuple[uuid.UUID, int]]:
        if self._session_factory is None:
            return []
        async with self._session_factory() as session:
            rows = await session.execute(
                select(User.id, User.telegram_user_id).where(User.telegram_user_id.is_not(None)).order_by(User.login)
            )
            return [(user_id, telegram_id) for user_id, telegram_id in rows if telegram_id is not None]

    async def _in_group(self, telegram_id: int) -> bool:
        """Состоит ли человек в общем чате. Не удалось узнать — считаем, что нет: лучше дубль, чем пропуск."""
        try:
            body = await self._call("getChatMember", {"chat_id": self._chat_id, "user_id": telegram_id})
        except (httpx.HTTPError, ValueError):
            return False
        member = body.get("result") or {}
        status = member.get("status")
        return bool(body.get("ok")) and (
            status in IN_CHAT or (status == "restricted" and bool(member.get("is_member")))
        )

    async def _send_message(
        self, chat_id: str, content: dict[str, Any], *, user_id: uuid.UUID | None = None
    ) -> SendResult:
        payload = {"chat_id": chat_id, "parse_mode": "HTML", "disable_web_page_preview": True, **content}
        try:
            body = await self._call("sendMessage", payload)
        except (httpx.HTTPError, ValueError) as exc:  # сеть, таймаут или не-JSON ответ
            # Текст ошибки httpx может содержать URL с токеном бота — вырезаем его.
            reason = f"{exc.__class__.__name__}: {exc}".replace(self._token or "***", "***")
            logger.warning("Telegram недоступен: %s", reason)
            return SendResult(ok=False, error=f"Telegram недоступен: {reason}")
        if not body.get("ok"):
            return SendResult(ok=False, error=f"Telegram отклонил сообщение: {body.get('description', body)}")
        message = body["result"]
        sent = SentMessage(chat_id=message["chat"]["id"], message_id=message["message_id"], user_id=user_id)
        return SendResult(ok=True, telegram_message_id=message["message_id"], telegram_messages=(sent,))

    # ---------- после оплаты: заменить напоминания ----------

    async def sync(self, occurrence_id: uuid.UUID, *, today: date, pressed: tuple[int, int] | None = None) -> int:
        """Привести все сообщения напоминания к статусу периода: оплачен — «✅ Платёж оплачен» без кнопки,
        не оплачен (отметку сняли) — снова напоминание с кнопкой. pressed — сообщение, где нажали кнопку
        (оно могло уйти до того, как сообщения стали сохраняться). Возвращает число изменённых сообщений."""
        if not self._token or self._session_factory is None:
            return 0
        payer = aliased(User)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(PaymentOccurrence, RecurringPayment, payer)
                    .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
                    .outerjoin(payer, payer.id == PaymentOccurrence.paid_by)
                    .where(PaymentOccurrence.id == occurrence_id)
                )
            ).first()
            if row is None:
                return 0
            occurrence, payment, paid_by = row
            stored = await session.execute(
                select(TelegramMessage.chat_id, TelegramMessage.message_id, Notification.kind)
                .join(Notification, Notification.id == TelegramMessage.notification_id)
                .where(Notification.occurrence_id == occurrence_id)
            )
            targets = {(chat_id, message_id): kind for chat_id, message_id, kind in stored}
        if pressed is not None:
            targets.setdefault(pressed, next(iter(targets.values()), None) or _default_kind())

        edited = 0
        for (chat_id, message_id), kind in targets.items():
            if occurrence.status is OccurrenceStatus.PAID and occurrence.paid_date is not None:
                content: dict[str, Any] = {
                    "text": paid_text_html(
                        payment_name=payment.name,
                        amount=occurrence.amount,
                        currency=occurrence.currency.value,
                        due_date=occurrence.due_date,
                        payer=(paid_by.full_name or paid_by.login) if paid_by else "—",
                        paid_date=occurrence.paid_date,
                    )
                }  # без reply_markup — кнопка «Оплачено» исчезает
            else:
                reminder = Reminder(
                    occurrence_id=occurrence.id,
                    kind=kind,
                    payment_name=payment.name,
                    amount=occurrence.amount,
                    currency=occurrence.currency,
                    due_date=occurrence.due_date,
                    today=today,
                )
                content = {
                    "text": reminder_text_html(reminder),
                    "reply_markup": reminder_keyboard(reminder, self._panel_url),
                }
            edited += await self._edit(chat_id, message_id, content)
        return edited

    async def _edit(self, chat_id: int, message_id: int, content: dict[str, Any]) -> int:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            **content,
        }
        try:
            body = await self._call("editMessageText", payload)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Telegram: сообщение %s/%s не изменено: %s", chat_id, message_id, exc.__class__.__name__)
            return 0
        if body.get("ok"):
            return 1
        description = str(body.get("description", ""))
        if "message is not modified" not in description:  # уже в нужном виде — не ошибка
            logger.info("Telegram: сообщение %s/%s не изменено: %s", chat_id, message_id, description)
        return 0


def _default_kind() -> NotificationKind:
    return NotificationKind.BEFORE_DUE
