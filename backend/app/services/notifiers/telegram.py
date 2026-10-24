import logging
from typing import Any

import httpx

from app.domain.enums import NotificationChannel
from app.services.notifiers.base import Reminder, SendResult
from app.services.notifiers.formatting import reminder_text_html

TELEGRAM_API = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10
NOT_CONFIGURED = "Telegram не настроен: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env"

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Отправляет напоминание в Telegram-чат через Bot API (sendMessage)."""

    channel = NotificationChannel.TELEGRAM

    def __init__(
        self, token: str | None, chat_id: str | None, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._transport = transport

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=TELEGRAM_API, timeout=SEND_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            response = await client.post(f"/bot{self._token}/{method}", json=payload)
        body: dict[str, Any] = response.json()
        return body

    async def send(self, reminder: Reminder) -> SendResult:
        if not self._token or not self._chat_id:
            return SendResult(ok=False, error=NOT_CONFIGURED, attempted=False)
        payload = {
            "chat_id": self._chat_id,
            "text": reminder_text_html(reminder),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
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
