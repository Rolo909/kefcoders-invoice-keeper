import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.enums import Currency, NotificationChannel, NotificationKind


@dataclass(frozen=True)
class Reminder:
    """Что сообщить: название, сумма, валюта и дата оплаты (требование кейса к напоминанию)."""

    occurrence_id: uuid.UUID
    kind: NotificationKind
    payment_name: str
    amount: Decimal
    currency: Currency
    due_date: date
    today: date


@dataclass(frozen=True)
class SentMessage:
    """Сообщение в Telegram: в общем чате (user_id = None) или в личке пользователю."""

    chat_id: int
    message_id: int
    user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None
    # False — канал не настроен: попытка не считается, и после настройки напоминание уйдёт.
    attempted: bool = True
    telegram_message_id: int | None = None
    # Все отправленные сообщения — чтобы после оплаты заменить каждое на «оплачено».
    telegram_messages: tuple[SentMessage, ...] = ()


class Notifier(Protocol):
    channel: NotificationChannel

    async def send(self, reminder: Reminder) -> SendResult: ...

    async def check(self) -> SendResult:
        """Проверочное сообщение — кнопка «Тестовое сообщение» в журнале панели."""
        ...
