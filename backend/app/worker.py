"""Фоновый процесс: сам проверяет сроки и отправляет напоминания (TASK_PLAN §8).

Запуск: `python -m app.worker` (отдельный сервис worker в docker-compose).
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete

from app.bot.runner import build_dispatcher, run_bot
from app.config import Settings, get_settings
from app.db import engine, session_factory
from app.domain.status import today_in
from app.models import Session, TelegramLinkCode
from app.services.occurrences import ensure_occurrences
from app.services.reminders import ReminderDispatcher, build_notifiers

logger = logging.getLogger("app.worker")


async def create_periods(settings: Settings) -> None:
    """Досоздать периоды по расписанию — чтобы напоминания были, даже если панель никто не открывал."""
    async with session_factory() as session:
        await ensure_occurrences(
            session, today=today_in(settings.timezone), horizon_days=settings.occurrence_horizon_days
        )
        await session.commit()


async def cleanup_expired() -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        await session.execute(delete(Session).where(Session.expires_at < now))
        await session.execute(delete(TelegramLinkCode).where(TelegramLinkCode.expires_at < now))
        await session.commit()


def _logged(name: str, job: Callable[[], Awaitable[object]]) -> Callable[[], Awaitable[None]]:
    """Ошибка задачи пишется в лог и не останавливает планировщик."""

    async def run() -> None:
        try:
            result = await job()
            logger.debug("%s: %s", name, result)
        except Exception:
            logger.exception("Задача «%s» завершилась с ошибкой", name)

    return run


def build_scheduler(settings: Settings, dispatcher: ReminderDispatcher) -> AsyncIOScheduler:
    async def reminders_tick() -> int:
        await create_periods(settings)
        return await dispatcher.run()

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _logged("напоминания", reminders_tick),
        IntervalTrigger(minutes=settings.reminder_check_interval_minutes),
        next_run_time=datetime.now(settings.timezone),  # первая проверка — сразу при старте
        max_instances=1,
        coalesce=True,
        id="reminders",
    )
    scheduler.add_job(_logged("очистка сессий", cleanup_expired), CronTrigger(hour=3), max_instances=1, id="cleanup")
    return scheduler


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    notifiers = build_notifiers(settings)
    dispatcher = ReminderDispatcher(
        session_factory, notifiers, remind_days_before=settings.remind_days_before, timezone=settings.timezone
    )
    scheduler = build_scheduler(settings, dispatcher)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # Windows: остановка по Ctrl+C
            loop.add_signal_handler(sig, stop.set)

    scheduler.start()
    logger.info(
        "Worker запущен: напоминания за %d дн., проверка каждые %d мин., каналы: %s",
        settings.remind_days_before,
        settings.reminder_check_interval_minutes,
        ", ".join(n.channel.value for n in notifiers) or "нет",
    )
    bot_task = _start_bot(settings)
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        if bot_task is not None:
            bot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bot_task
        await engine.dispose()
        logger.info("Worker остановлен")


def _start_bot(settings: Settings) -> asyncio.Task[None] | None:
    """Бот (кнопка «Оплачено», /link) работает, только если задан токен; иначе worker просто напоминает."""
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        logger.info("Telegram-бот не запущен: TELEGRAM_BOT_TOKEN не задан")
        return None
    dispatcher = build_dispatcher(session_factory, settings.timezone)
    task = asyncio.create_task(run_bot(settings.telegram_bot_token.get_secret_value(), dispatcher))
    task.add_done_callback(_log_bot_exit)
    return task


def _log_bot_exit(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Telegram-бот остановился с ошибкой", exc_info=task.exception())


if __name__ == "__main__":
    asyncio.run(main())
