"""Защита бота от флуда: не больше max_updates сообщений и нажатий от одного человека за окно.

Бот работает через long polling — входящих портов у него нет, и «положить» его запросами из интернета нельзя.
Но кто угодно может засыпать его сообщениями в личке или нажатиями в чате; каждое такое событие — запрос к БД.
Лишние события молча отбрасываются.
"""

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User


class FloodGuard(BaseMiddleware):
    def __init__(
        self, max_updates: int = 10, window_seconds: float = 10, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max_updates = max_updates
        self._window = window_seconds
        self._clock = clock
        self._recent: dict[int, deque[float]] = {}

    def allow(self, user_id: int) -> bool:
        now = self._clock()
        recent = self._recent.setdefault(user_id, deque())
        while recent and recent[0] <= now - self._window:
            recent.popleft()
        if len(recent) >= self._max_updates:
            return False
        recent.append(now)
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and not self.allow(user.id):
            return None
        return await handler(event, data)
