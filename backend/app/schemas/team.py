import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_MAX_LENGTH = 100
NAME_RULE = f"Название команды — от 1 до {NAME_MAX_LENGTH} символов"
CHAT_RULE = "ID чата — число, например -1001234567890, или @имя_канала"
# Как в форме панели: id группы или канала (у супергрупп — с -100) либо публичное @имя.
CHAT_PATTERN = re.compile(r"-?\d{5,20}|@[A-Za-z0-9_]{5,32}")


def _check_name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > NAME_MAX_LENGTH:
        raise ValueError(NAME_RULE)
    return name


def _check_chat(value: str | None) -> str | None:
    chat = (value or "").strip()
    if not chat:
        return None  # пусто — напоминания в TELEGRAM_CHAT_ID из .env
    if CHAT_PATTERN.fullmatch(chat) is None:
        raise ValueError(CHAT_RULE)
    return chat


class TeamBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class TeamOut(TeamBrief):
    telegram_chat_id: str | None = Field(description="Чат напоминаний команды; null — общий чат из .env")
    members_count: int
    created_at: datetime


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    telegram_chat_id: str | None = None

    _name = field_validator("name")(_check_name)
    _chat = field_validator("telegram_chat_id")(_check_chat)


class TeamUpdate(BaseModel):
    """Частичное изменение: учитываются только переданные поля."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    telegram_chat_id: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _check_name(value)

    _chat = field_validator("telegram_chat_id")(_check_chat)
