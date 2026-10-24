import ipaddress
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.domain.enums import NotificationChannel
from app.services.notifiers.base import Reminder, SendResult
from app.services.notifiers.formatting import reminder_text_html
from app.services.telegram import pay_callback_data

TELEGRAM_API = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10
NOT_CONFIGURED = "Telegram не настроен: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env"
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
    """Отправляет напоминание в Telegram-чат через Bot API (sendMessage)."""

    channel = NotificationChannel.TELEGRAM

    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
        *,
        public_web_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._panel_url = public_panel_url(public_web_url)
        self._transport = transport

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=TELEGRAM_API, timeout=SEND_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            response = await client.post(f"/bot{self._token}/{method}", json=payload)
        body: dict[str, Any] = response.json()
        return body

    async def send(self, reminder: Reminder) -> SendResult:
        return await self._send_message(
            {"text": reminder_text_html(reminder), "reply_markup": reminder_keyboard(reminder, self._panel_url)}
        )

    async def check(self) -> SendResult:
        return await self._send_message({"text": CHECK_TEXT})

    async def _send_message(self, content: dict[str, Any]) -> SendResult:
        if not self._token or not self._chat_id:
            return SendResult(ok=False, error=NOT_CONFIGURED, attempted=False)
        payload = {"chat_id": self._chat_id, "parse_mode": "HTML", "disable_web_page_preview": True, **content}
        try:
            body = await self._call("sendMessage", payload)
        except (httpx.HTTPError, ValueError) as exc:  # сеть, таймаут или не-JSON ответ
            # Текст ошибки httpx может содержать URL с токеном бота — вырезаем его.
            reason = f"{exc.__class__.__name__}: {exc}".replace(self._token, "***")
            logger.warning("Telegram недоступен: %s", reason)
            return SendResult(ok=False, error=f"Telegram недоступен: {reason}")
        if not body.get("ok"):
            return SendResult(ok=False, error=f"Telegram отклонил сообщение: {body.get('description', body)}")
        return SendResult(ok=True, telegram_message_id=body["result"]["message_id"])
