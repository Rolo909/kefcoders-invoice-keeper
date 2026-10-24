"""Напоминания об оплате (TASK_PLAN §4.5): минимум за N дней до срока, без дублей, только неоплаченные.

Защита от дублей держится на базе данных, а не на памяти процесса: уникальный ключ
(период, канал, тип) в notifications. Отправку «забирают» атомарным INSERT … ON CONFLICT DO NOTHING
(или UPDATE для повтора после ошибки) — поэтому повторная или параллельная проверка (worker и API)
не отправит второе сообщение.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy import ColumnElement, and_, exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import SessionFactory
from app.domain.enums import NotificationChannel, NotificationKind, NotificationStatus, OccurrenceStatus
from app.domain.status import today_in
from app.models import Notification, PaymentOccurrence, RecurringPayment, TelegramMessage
from app.services.notifiers.base import Notifier, Reminder, SendResult
from app.services.notifiers.email import EmailNotifier
from app.services.notifiers.inapp import InAppNotifier
from app.services.notifiers.telegram import TelegramNotifier
from app.services.notifiers.webhook import WebhookNotifier

MAX_ATTEMPTS = 5
# Отправка, начатая упавшим процессом, через это время забирается заново.
STALE_CLAIM = timedelta(minutes=5)
# Сообщение о просрочке — один раз, если срок прошёл не больше этого числа дней назад.
OVERDUE_LOOKBACK_DAYS = 3
CHANNEL_DISABLED = {
    NotificationChannel.TELEGRAM: "Канал выключен: TELEGRAM_ENABLED=false",
    NotificationChannel.EMAIL: "Канал выключен: EMAIL_ENABLED=false",
    NotificationChannel.WEBHOOK: "WEBHOOK_URL не задан",
    NotificationChannel.INAPP: "Канал выключен: INAPP_ENABLED=false",
}


Occ = PaymentOccurrence
_channel_type = Notification.__table__.c.channel.type
_kind_type = Notification.__table__.c.kind.type
_status_type = Notification.__table__.c.status.type

logger = logging.getLogger(__name__)


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


def build_notifiers(settings: Settings, session_factory: SessionFactory) -> list[Notifier]:
    """Включённые каналы. Сбой одного канала не мешает остальным — у каждого своя запись в журнале."""
    notifiers: list[Notifier] = []
    if settings.telegram_enabled:
        notifiers.append(
            TelegramNotifier(
                _secret(settings.telegram_bot_token),
                settings.telegram_chat_id,
                public_web_url=settings.public_web_url,
                session_factory=session_factory,
            )
        )
    if settings.email_enabled:
        notifiers.append(
            EmailNotifier(
                session_factory,
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.smtp_from,
                username=settings.smtp_user,
                password=_secret(settings.smtp_password),
                start_tls=settings.smtp_tls,
                extra_recipients=settings.extra_email_recipients,
            )
        )
    if settings.webhook_url:
        notifiers.append(WebhookNotifier(settings.webhook_url, _secret(settings.webhook_secret)))
    if settings.inapp_enabled:
        notifiers.append(InAppNotifier())
    return notifiers


def _still_due(occurrence_id: uuid.UUID) -> list[ColumnElement[bool]]:
    """Условия «напоминать ещё нужно»: период не оплачен, платёж не прекращён."""
    return [
        Occ.id == occurrence_id,
        Occ.status == OccurrenceStatus.UNPAID,
        RecurringPayment.deleted_at.is_(None),
        RecurringPayment.is_active.is_(True),
    ]


async def _claim(
    session: AsyncSession, occurrence_id: uuid.UUID, channel: NotificationChannel, kind: NotificationKind
) -> uuid.UUID | None:
    """Забрать отправку себе. None — уже отправлено, отправляется другим процессом или больше не нужно."""
    fresh = (
        pg_insert(Notification)
        .from_select(
            ["occurrence_id", "channel", "kind", "status", "claimed_at"],
            select(
                Occ.id,
                literal(channel, _channel_type),
                literal(kind, _kind_type),
                literal(NotificationStatus.PENDING, _status_type),
                func.now(),
            )
            .join(RecurringPayment, RecurringPayment.id == Occ.recurring_payment_id)
            .where(*_still_due(occurrence_id)),
        )
        .on_conflict_do_nothing(index_elements=["occurrence_id", "channel", "kind"])
        .returning(Notification.id)
    )
    claimed = await session.scalar(fresh)
    if claimed is not None:
        return claimed

    retry = (
        update(Notification)
        .where(
            Notification.occurrence_id == occurrence_id,
            Notification.channel == channel,
            Notification.kind == kind,
            or_(
                and_(Notification.status == NotificationStatus.FAILED, Notification.attempts < MAX_ATTEMPTS),
                and_(
                    Notification.status == NotificationStatus.PENDING,
                    Notification.claimed_at < func.now() - STALE_CLAIM,
                ),
            ),
            exists(
                select(Occ.id)
                .join(RecurringPayment, RecurringPayment.id == Occ.recurring_payment_id)
                .where(*_still_due(occurrence_id))
            ),
        )
        .values(status=NotificationStatus.PENDING, claimed_at=func.now())
        .returning(Notification.id)
    )
    return await session.scalar(retry)


async def _store_result(session: AsyncSession, notification_id: uuid.UUID, result: SendResult) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(
            status=NotificationStatus.SENT if result.ok else NotificationStatus.FAILED,
            attempts=Notification.attempts + (1 if result.attempted else 0),
            last_error=result.error,
            sent_at=func.now() if result.ok else None,
            telegram_message_id=result.telegram_message_id,
        )
    )
    if result.telegram_messages:
        await session.execute(
            pg_insert(TelegramMessage)
            .values(
                [
                    {
                        "notification_id": notification_id,
                        "chat_id": m.chat_id,
                        "message_id": m.message_id,
                        "user_id": m.user_id,
                    }
                    for m in result.telegram_messages
                ]
            )
            .on_conflict_do_nothing(index_elements=["notification_id", "chat_id"])
        )


async def _candidates(
    session: AsyncSession, *, today: date, remind_days_before: int, payment_id: uuid.UUID | None
) -> list[tuple[PaymentOccurrence, RecurringPayment, NotificationKind]]:
    windows = {
        NotificationKind.BEFORE_DUE: (today, today + timedelta(days=remind_days_before)),
        NotificationKind.OVERDUE: (today - timedelta(days=OVERDUE_LOOKBACK_DAYS), today - timedelta(days=1)),
    }
    found = []
    for kind, (start, end) in windows.items():
        stmt = (
            select(Occ, RecurringPayment)
            .join(RecurringPayment, RecurringPayment.id == Occ.recurring_payment_id)
            .where(
                Occ.status == OccurrenceStatus.UNPAID,
                RecurringPayment.deleted_at.is_(None),
                RecurringPayment.is_active,
                Occ.due_date.between(start, end),
            )
            .order_by(Occ.due_date)
        )
        if payment_id is not None:
            stmt = stmt.where(Occ.recurring_payment_id == payment_id)
        found += [(occurrence, payment, kind) for occurrence, payment in await session.execute(stmt)]
    return found


class ReminderDispatcher:
    def __init__(
        self,
        session_factory: SessionFactory,
        notifiers: Sequence[Notifier],
        *,
        remind_days_before: int,
        timezone: ZoneInfo,
    ) -> None:
        self._session_factory = session_factory
        self._notifiers = notifiers
        self._remind_days_before = remind_days_before
        self._timezone = timezone

    async def check_channels(self) -> list[tuple[NotificationChannel, SendResult]]:
        """Проверочное сообщение в каждый канал; выключенные — с причиной (кнопка «Тестовое сообщение»)."""
        enabled = {notifier.channel: notifier for notifier in self._notifiers}
        results = []
        for channel in NotificationChannel:
            notifier = enabled.get(channel)
            if notifier is None:
                results.append((channel, SendResult(ok=False, error=CHANNEL_DISABLED[channel], attempted=False)))
                continue
            try:
                results.append((channel, await notifier.check()))
            except Exception as exc:  # проверка одного канала не должна мешать остальным
                logger.exception("Проверка канала %s не удалась", channel)
                results.append((channel, SendResult(ok=False, error=f"{exc.__class__.__name__}: {exc}")))
        return results

    async def sync_telegram(self, occurrence_id: uuid.UUID, *, pressed: tuple[int, int] | None = None) -> int:
        """Заменить сообщения напоминания в Telegram на «оплачено» или вернуть напоминание с кнопкой.

        Вызывается после отметки или снятия оплаты — в панели и кнопкой в боте.
        """
        edited = 0
        for notifier in self._notifiers:
            if isinstance(notifier, TelegramNotifier):
                try:
                    edited += await notifier.sync(occurrence_id, today=today_in(self._timezone), pressed=pressed)
                except Exception:  # Telegram недоступен — оплата уже сохранена, сообщения поправятся вручную
                    logger.exception("Не удалось обновить сообщения Telegram по периоду %s", occurrence_id)
        return edited

    async def run(self, *, today: date | None = None, payment_id: uuid.UUID | None = None) -> int:
        """Отправить все положенные напоминания (или только по одному платежу). Возвращает число отправленных."""
        day = today or today_in(self._timezone)
        sent = 0
        async with self._session_factory() as session:
            candidates = await _candidates(
                session, today=day, remind_days_before=self._remind_days_before, payment_id=payment_id
            )
            for occurrence, payment, kind in candidates:
                reminder = Reminder(
                    occurrence_id=occurrence.id,
                    kind=kind,
                    payment_name=payment.name,
                    amount=occurrence.amount,
                    currency=occurrence.currency,
                    due_date=occurrence.due_date,
                    today=day,
                )
                for notifier in self._notifiers:
                    sent += await self._deliver(session, notifier, reminder)
        return sent

    async def _deliver(self, session: AsyncSession, notifier: Notifier, reminder: Reminder) -> int:
        notification_id = await _claim(session, reminder.occurrence_id, notifier.channel, reminder.kind)
        await session.commit()  # отметка «забрано» видна другим процессам до отправки
        if notification_id is None:
            return 0
        try:
            result = await notifier.send(reminder)
        except Exception as exc:  # сбой одного канала не должен останавливать остальные напоминания
            logger.exception("Канал %s: ошибка отправки", notifier.channel)
            result = SendResult(ok=False, error=f"{exc.__class__.__name__}: {exc}")
        await _store_result(session, notification_id, result)
        await session.commit()
        if not result.ok:
            logger.warning(
                "Напоминание %s не отправлено (%s): %s", reminder.occurrence_id, notifier.channel, result.error
            )
        return 1 if result.ok else 0
