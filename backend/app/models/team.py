from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import CreatedAtMixin, UuidPkMixin


class Team(UuidPkMixin, CreatedAtMixin, Base):
    """Команда: свои участники, платежи, периоды общих платежей, бюджеты и Telegram-чат."""

    __tablename__ = "teams"
    __table_args__ = (
        # Название уникально без учёта регистра: «Kefcoders» и «kefcoders» — одна команда.
        Index("uq_teams_name_lower", text("lower(name)"), unique=True),
    )

    name: Mapped[str] = mapped_column(String(100))
    # Число (-1001234567890) или @имя_канала; пусто — напоминания в TELEGRAM_CHAT_ID из .env.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
