import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.enums import NotificationChannel
from app.services.notifiers.base import Reminder, SendResult, TeamTarget

SEND_TIMEOUT_SECONDS = 5
SIGNATURE_HEADER = "X-InvoiceKeeper-Signature"
EVENT_HEADER = "X-InvoiceKeeper-Event"

logger = logging.getLogger(__name__)


def signature(body: bytes, secret: str) -> str:
    """sha256=<hex HMAC тела запроса> — получатель проверяет, что запрос пришёл от Invoice Keeper."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookNotifier:
    """POST JSON на WEBHOOK_URL; с WEBHOOK_SECRET запрос подписывается HMAC-SHA256."""

    channel = NotificationChannel.WEBHOOK

    def __init__(
        self, url: str, secret: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._url = url
        self._secret = secret
        self._transport = transport

    async def send(self, reminder: Reminder) -> SendResult:
        return await self._post(
            "payment.reminder",
            {
                "kind": reminder.kind.value,
                "occurrence": {
                    "id": str(reminder.occurrence_id),
                    "due_date": reminder.due_date.isoformat(),
                    "amount": str(reminder.amount),
                    "currency": reminder.currency.value,
                },
                "payment": {"name": reminder.payment_name},
                "team": {"id": str(reminder.team.id), "name": reminder.team.name},
            },
        )

    async def check(self, team: TeamTarget | None = None) -> SendResult:
        return await self._post("test", {})

    async def _post(self, event: str, data: dict[str, Any]) -> SendResult:
        payload = {"event": event, "sent_at": datetime.now(UTC).isoformat(), **data}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "InvoiceKeeper", EVENT_HEADER: event}
        if self._secret:
            headers[SIGNATURE_HEADER] = signature(body, self._secret)
        try:
            async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(self._url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            # Адрес в текст ошибки не попадает: в нём может быть ключ получателя.
            logger.warning("Webhook недоступен: %s", exc.__class__.__name__)
            return SendResult(ok=False, error=f"Webhook недоступен: {exc.__class__.__name__}")
        if not response.is_success:
            return SendResult(ok=False, error=f"Webhook ответил кодом {response.status_code}")
        return SendResult(ok=True)
