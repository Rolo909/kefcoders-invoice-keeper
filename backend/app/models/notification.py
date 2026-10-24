import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.enums import NotificationChannel, NotificationKind, NotificationStatus
from app.models.base import CreatedAtMixin, UuidPkMixin, pg_enum


class Notification(UuidPkMixin, CreatedAtMixin, Base):
    """Журнал напоминаний; уникальный ключ (период, канал, тип) исключает дубли."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("occurrence_id", "channel", "kind"),
        Index("ix_notifications_channel_status", "channel", "status"),
    )

    occurrence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_occurrences.id", ondelete="CASCADE"))
    channel: Mapped[NotificationChannel] = mapped_column(pg_enum(NotificationChannel, "notification_channel"))
    kind: Mapped[NotificationKind] = mapped_column(pg_enum(NotificationKind, "notification_kind"))
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"),
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    # Когда отправку забрал процесс: зависшая «pending»-запись (процесс упал) забирается повторно.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationRead(Base):
    """Отметка «прочитано» уведомления в веб-панели — у каждого пользователя своя."""

    __tablename__ = "notification_reads"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramMessage(UuidPkMixin, CreatedAtMixin, Base):
    """Сообщение с напоминанием в Telegram: в общем чате или в личке тому, кого в чате нет.

    Нужны все, чтобы после оплаты (в панели или кнопкой) заменить каждое на «оплачено», а при снятии
    отметки — вернуть напоминание с кнопкой.
    """

    __tablename__ = "telegram_messages"
    __table_args__ = (UniqueConstraint("notification_id", "chat_id"),)

    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    # Кому ушло в личку; None — общий чат.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
