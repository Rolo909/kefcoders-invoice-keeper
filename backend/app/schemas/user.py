import re
import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import Role

LOGIN_PATTERN = re.compile(r"^[a-z0-9._-]{3,64}$", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"^\S+@\S+\.\S+$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
FULL_NAME_MAX_LENGTH = 128
EMAIL_MAX_LENGTH = 255

LOGIN_RULE = "Логин — от 3 до 64 латинских букв, цифр, точек, дефисов или подчёркиваний"
PASSWORD_RULE = f"Пароль — от {PASSWORD_MIN_LENGTH} до {PASSWORD_MAX_LENGTH} символов"
EMAIL_RULE = "Введите адрес почты целиком, например name@kefcoders.ru"
EMAIL_REQUIRED_FOR_NOTIFY = "Укажите почту, чтобы получать на неё напоминания"


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _check_login(value: str) -> str:
    login = value.strip()
    if not LOGIN_PATTERN.fullmatch(login):
        raise ValueError(LOGIN_RULE)
    return login


def _check_password(value: str) -> str:
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise ValueError(PASSWORD_RULE)
    return value


def _check_full_name(value: str | None) -> str | None:
    name = _blank_to_none(value)
    if name is not None and len(name) > FULL_NAME_MAX_LENGTH:
        raise ValueError(f"ФИО — не длиннее {FULL_NAME_MAX_LENGTH} символов")
    return name


def _check_email(value: str | None) -> str | None:
    email = _blank_to_none(value)
    if email is not None and (len(email) > EMAIL_MAX_LENGTH or not EMAIL_PATTERN.fullmatch(email)):
        raise ValueError(EMAIL_RULE)
    return email


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    login: str
    full_name: str | None


class UserOut(UserBrief):
    email: str | None
    role: Role
    is_system: bool
    telegram_linked: bool
    notify_email: bool
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    server_today: date = Field(description="«Сегодня» в часовом поясе приложения")
    timezone: str


class UserCreate(BaseModel):
    """Создаётся только обычный пользователь: роли в запросе нет, лишние поля отклоняются."""

    model_config = ConfigDict(extra="forbid")

    login: str
    password: str
    team_id: uuid.UUID = Field(description="Команда пользователя — обязательна")
    full_name: str | None = None
    email: str | None = None
    notify_email: bool = False

    _login = field_validator("login")(_check_login)
    _password = field_validator("password")(_check_password)
    _full_name = field_validator("full_name")(_check_full_name)
    _email = field_validator("email")(_check_email)

    @model_validator(mode="after")
    def _email_required_for_notify(self) -> Self:
        if self.notify_email and self.email is None:
            raise ValueError(EMAIL_REQUIRED_FOR_NOTIFY)
        return self


class UserUpdate(BaseModel):
    """Частичное изменение: учитываются только переданные поля; пустой пароль — «не менять»."""

    model_config = ConfigDict(extra="forbid")

    login: str | None = None
    password: str | None = None
    team_id: uuid.UUID | None = Field(default=None, description="Перевод в другую команду; прошлые отметки остаются")
    full_name: str | None = None
    email: str | None = None
    notify_email: bool | None = None

    @field_validator("login")
    @classmethod
    def _login(cls, value: str | None) -> str | None:
        return None if value is None else _check_login(value)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str | None) -> str | None:
        return None if not value else _check_password(value)

    _full_name = field_validator("full_name")(_check_full_name)
    _email = field_validator("email")(_check_email)


class ProfileUpdate(BaseModel):
    """Пользователь сам меняет свою почту для напоминаний (страница «Настройки» панели)."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    notify_email: bool = False

    _email = field_validator("email")(_check_email)

    @model_validator(mode="after")
    def _email_required_for_notify(self) -> Self:
        if self.notify_email and self.email is None:
            raise ValueError(EMAIL_REQUIRED_FOR_NOTIFY)
        return self
