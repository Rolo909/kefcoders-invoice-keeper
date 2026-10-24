"""Запуск бота в режиме long polling внутри процесса worker."""

import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.bot.flood import FloodGuard
from app.bot.handlers import build_router
from app.db import SessionFactory
from app.services.reminders import ReminderDispatcher

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Что умеет бот"),
    BotCommand(command="link", description="Привязать аккаунт панели: /link <код>"),
]


def build_dispatcher(
    session_factory: SessionFactory, timezone: ZoneInfo, reminders: ReminderDispatcher | None = None
) -> Dispatcher:
    """reminders — чтобы кнопка «Оплачено» заменила все копии напоминания на «оплачено»."""
    dispatcher = Dispatcher(session_factory=session_factory, timezone=timezone, reminders=reminders)
    guard = FloodGuard()
    dispatcher.message.outer_middleware(guard)
    dispatcher.callback_query.outer_middleware(guard)
    dispatcher.include_router(build_router())
    return dispatcher


async def run_bot(token: str, dispatcher: Dispatcher) -> None:
    bot = Bot(token)
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.delete_webhook()  # если боту когда-то ставили webhook, getUpdates вернул бы 409
        logger.info("Telegram-бот запущен: кнопка «Оплачено» и /link работают")
        await dispatcher.start_polling(bot, handle_signals=False, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
