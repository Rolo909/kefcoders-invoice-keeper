"""Логирование всех процессов (API, worker, bootstrap, seed): единый формат и никаких секретов в логах.

Токен Telegram-бота входит в адрес запросов к Bot API (https://api.telegram.org/bot<токен>/…),
а httpx на уровне INFO логирует каждый запрос вместе с адресом. Поэтому httpx и httpcore пишут
только предупреждения, а фильтр на всякий случай маскирует всё, что похоже на токен, в любой записи.
"""

import logging
import re

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# Токен бота: числовой id, двоеточие и секрет из 30+ символов.
BOT_TOKEN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
MASK = "***"
# Логируют адреса запросов, а в них — токен бота.
NOISY_LOGGERS = ("httpx", "httpcore")


class HideSecrets(logging.Filter):
    """Заменяет токены ботов в тексте записи на ***."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if BOT_TOKEN.search(message):
            record.msg, record.args = BOT_TOKEN.sub(MASK, message), ()
        return True


def configure_logging(level: str | int) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, HideSecrets) for f in handler.filters):
            handler.addFilter(HideSecrets())
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
