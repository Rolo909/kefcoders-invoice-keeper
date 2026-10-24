from enum import StrEnum


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class Period(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class OccurrenceStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"


class OccurrenceState(StrEnum):
    """Вычисляемое состояние периода для UI и фильтров."""

    PAID = "paid"
    PAID_LATE = "paid_late"
    OVERDUE = "overdue"
    DUE_SOON = "due_soon"
    UPCOMING = "upcoming"


class NotificationChannel(StrEnum):
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"
    INAPP = "inapp"


class NotificationKind(StrEnum):
    BEFORE_DUE = "before_due"
    OVERDUE = "overdue"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class AttachmentKind(StrEnum):
    FILE = "file"
    LINK = "link"


class BudgetPeriodType(StrEnum):
    MONTH = "month"
    YEAR = "year"
