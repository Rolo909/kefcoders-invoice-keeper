import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.enums import Currency, NotificationChannel, NotificationKind


@dataclass(frozen=True)
class TeamTarget:
    """Команда, которой адресовано сообщение: её чат, её участники."""

    id: uuid.UUID
    name: str
    telegram_chat_id: str | None  # None — общий чат TELEGRAM_CHAT_ID из .env


@dataclass(frozen=True)
class Reminder:
    """Что сообщить: название, сумма, валюта и дата оплаты (требование кейса к напоминанию) — и какой команде."""

    occurrence_id: uuid.UUID
    team: TeamTarget
    kind: NotificationKind
    payment_name: str
    amount: Decimal
    currency: Currency
    due_date: date
    today: date


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None
    # False — канал не настроен: попытка не считается, и после настройки напоминание уйдёт.
    attempted: bool = True
    telegram_message_id: int | None = None


class Notifier(Protocol):
    channel: NotificationChannel

    async def send(self, reminder: Reminder) -> SendResult: ...

    async def check(self, team: TeamTarget | None = None) -> SendResult:
        """Проверочное сообщение — кнопка «Тестовое сообщение» в журнале панели; team — проверить канал команды."""
        ...
