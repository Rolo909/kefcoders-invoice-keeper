"""Все модели — импорт здесь регистрирует таблицы в Base.metadata (нужно Alembic)."""

from app.models.attachment import Attachment
from app.models.audit import AuditLog
from app.models.budget import Budget
from app.models.notification import Notification, NotificationRead
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.models.team import Team
from app.models.user import Session, TelegramLinkCode, User

__all__ = [
    "Attachment",
    "AuditLog",
    "Budget",
    "Notification",
    "NotificationRead",
    "PaymentOccurrence",
    "RecurringPayment",
    "Session",
    "Team",
    "TelegramLinkCode",
    "User",
]
