"""Пароли (argon2) и токены сессий."""

import hashlib
import secrets

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

_hasher = PasswordHash.recommended()
# Хеш, с которым не совпадёт ни один пароль: так блокируется вход бывшему системному админу.
LOCKED_PASSWORD_HASH = "!locked"  # noqa: S105 — заведомо невалидный хеш, не пароль
# Хеш для несуществующего логина: проверка занимает столько же времени, сколько для настоящего,
# поэтому по времени ответа нельзя узнать, существует ли пользователь.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

SESSION_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False
    try:
        return _hasher.verify(password, password_hash)
    except PwdlibError:  # неизвестный формат хеша — например, заблокированная учётная запись
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """В БД хранится только sha256 токена: утечка таблицы sessions не даёт войти."""
    return hashlib.sha256(token.encode()).hexdigest()
