import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.enums import Role
from app.models.base import CreatedAtMixin, UuidPkMixin, pg_enum


class User(UuidPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Логин уникален без учёта регистра: «Anna» и «anna» — один пользователь.
        Index("uq_users_login_lower", text("lower(login)"), unique=True),
        # Системный админ из .env ровно один.
        Index("uq_users_single_system", "is_system", unique=True, postgresql_where=text("is_system")),
        # Администратор не состоит в команде. Команду обычного пользователя требует API (422 без неё);
        # без команды остаётся только прежний админ, снятый при смене ADMIN_LOGIN, — он не может войти.
        CheckConstraint("role = 'user' OR team_id IS NULL", name="team_matches_role"),
    )

    login: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(pg_enum(Role, "user_role"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def telegram_linked(self) -> bool:
        return self.telegram_user_id is not None


class Session(UuidPkMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[str | None] = mapped_column(String(64))


class TelegramLinkCode(CreatedAtMixin, Base):
    __tablename__ = "telegram_link_codes"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
