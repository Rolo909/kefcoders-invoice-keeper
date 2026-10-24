from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from aiogram.types import TelegramObject

from app.bot.flood import FloodGuard


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_flood_from_one_user_is_dropped_but_others_pass() -> None:
    clock = FakeClock()
    guard = FloodGuard(max_updates=3, window_seconds=10, clock=clock)
    handler = AsyncMock(return_value="ok")

    async def press(user_id: int) -> Any:
        return await guard(handler, TelegramObject(), {"event_from_user": SimpleNamespace(id=user_id)})

    assert [await press(1) for _ in range(5)] == ["ok", "ok", "ok", None, None]
    assert await press(2) == "ok"  # другой человек не страдает
    assert handler.await_count == 4


def test_user_is_allowed_again_after_the_window() -> None:
    clock = FakeClock()
    guard = FloodGuard(max_updates=2, window_seconds=10, clock=clock)
    assert [guard.allow(1) for _ in range(3)] == [True, True, False]

    clock.now = 10.5

    assert guard.allow(1)


async def test_updates_without_user_are_not_limited() -> None:
    guard = FloodGuard(max_updates=1, window_seconds=10, clock=FakeClock())
    handler = AsyncMock(return_value="ok")

    assert [await guard(handler, TelegramObject(), {}) for _ in range(3)] == ["ok", "ok", "ok"]
