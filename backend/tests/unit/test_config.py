from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings

REQUIRED: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://u:p@db:5432/x",
    "admin_password": "long-enough",
}


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**REQUIRED, **overrides})


def test_defaults_match_case_requirements() -> None:
    settings = _settings()

    assert settings.remind_days_before == 3
    assert settings.app_timezone == "Europe/Moscow"
    assert settings.timezone.key == "Europe/Moscow"


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Неизвестный часовой пояс"):
        _settings(app_timezone="Mars/Olympus")


def test_reminder_earlier_than_three_days_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(remind_days_before=2)


def test_short_admin_password_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(admin_password="short")


def test_empty_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEBHOOK_URL", "")

    settings = _settings()

    assert settings.telegram_bot_token is None
    assert settings.webhook_url is None


def test_extra_email_recipients_are_split_and_trimmed() -> None:
    settings = _settings(email_extra_recipients=" a@x.ru, ,b@y.ru ")

    assert settings.extra_email_recipients == ["a@x.ru", "b@y.ru"]
