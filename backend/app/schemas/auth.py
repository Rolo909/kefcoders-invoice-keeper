from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.user import UserOut


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginOut(BaseModel):
    access_token: str = Field(description="Токен для заголовка Authorization: Bearer (браузер использует cookie)")
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — тип токена, не пароль
    expires_at: datetime
    user: UserOut
