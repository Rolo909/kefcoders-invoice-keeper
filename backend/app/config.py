from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_REMIND_DAYS_BEFORE = 3  # кейс: напоминание минимум за 3 дня до срока


class Settings(BaseSettings):
    """Настройки приложения из переменных окружения / .env (см. .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    app_timezone: str = "Europe/Moscow"
    public_web_url: str = "http://localhost:8080"
    remind_days_before: int = Field(default=MIN_REMIND_DAYS_BEFORE, ge=MIN_REMIND_DAYS_BEFORE)
    reminder_check_interval_minutes: int = Field(default=1, ge=1)
    occurrence_horizon_days: int = Field(default=60, ge=1)
    session_ttl_hours: int = Field(default=168, ge=1)
    seed_demo_data: bool = False
    log_level: str = "INFO"

    admin_login: str = Field(default="admin", min_length=3, max_length=64)
    admin_password: SecretStr = Field(min_length=8)

    database_url: str

    telegram_enabled: bool = True
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    email_enabled: bool = False
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "invoice-keeper@example.local"
    smtp_tls: bool = False
    email_extra_recipients: str = ""

    inapp_enabled: bool = True

    webhook_url: str | None = None
    webhook_secret: SecretStr | None = None

    upload_dir: str = "/data/uploads"
    upload_max_mb: int = Field(default=10, ge=1)

    @field_validator("app_timezone")
    @classmethod
    def _timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Неизвестный часовой пояс: {value}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level_upper(cls, value: str) -> str:
        return value.upper()

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def extra_email_recipients(self) -> list[str]:
        return [item.strip() for item in self.email_extra_recipients.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # обязательные поля приходят из окружения
