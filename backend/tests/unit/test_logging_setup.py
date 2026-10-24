import logging
from collections.abc import Iterator

import httpx
import pytest

from app.logging_setup import NOISY_LOGGERS, HideSecrets, configure_logging

TOKEN = "8217666632:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture(autouse=True)
def restore_levels() -> Iterator[None]:
    yield
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)


async def test_bot_api_requests_do_not_leak_token(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO")
    caplog.set_level(logging.INFO)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))

    async with httpx.AsyncClient(transport=transport) as client:
        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={})

    assert TOKEN not in caplog.text


def test_token_is_masked_in_any_record() -> None:
    record = logging.LogRecord("app", logging.WARNING, __file__, 1, "Ошибка запроса %s", (f"/bot{TOKEN}/x",), None)

    HideSecrets().filter(record)

    assert record.getMessage() == "Ошибка запроса /bot***/x"


def test_ordinary_numbers_are_left_alone() -> None:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "Чат -1001234567890, период 12:30", (), None)

    HideSecrets().filter(record)

    assert record.getMessage() == "Чат -1001234567890, период 12:30"
