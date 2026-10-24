"""Telegram-бот: /start, /link <код> и кнопка «✅ Оплачено» в напоминаниях.

Обработчики тонкие: вся логика — в app.services.telegram (её же проверяют тесты).
Зависимости session_factory и timezone приходят из данных Dispatcher (см. app.bot.runner).
"""

import contextlib
from datetime import UTC, date, datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.db import SessionFactory
from app.domain.status import today_in
from app.models import User
from app.services.notifiers.formatting import format_date
from app.services.reminders import ReminderDispatcher
from app.services.telegram import (
    PAY_CALLBACK_PREFIX,
    LinkResult,
    PayResult,
    link_account,
    mark_paid_from_telegram,
    parse_pay_callback,
)

START_TEXT = (
    "Я бот Invoice Keeper: напоминаю об оплате регулярных платежей за 3 дня до срока.\n\n"
    "Чтобы отмечать оплату кнопкой «✅ Оплачено», привяжите аккаунт: в панели откройте "
    "«Профиль» → Telegram → «Получить код» и пришлите мне здесь команду /link <код>."
)
LINK_IN_PRIVATE = "Код привязки отправляйте в личном чате со мной — так его не увидят другие участники группы."
LINK_USAGE = "Пришлите код из панели: /link 123456"
LINK_INVALID = "Код не подошёл: он неверный, уже использован или истёк. Получите новый в панели: «Профиль» → Telegram."
NOT_LINKED = (
    "Ваш Telegram не привязан к панели. Откройте «Профиль» → Telegram и пришлите мне в личном чате /link <код>."
)
NOT_FOUND = "Этот период не найден — возможно, платёж прекращён."
STALE_BUTTON = "Кнопка устарела."


def _display_name(user: User) -> str:
    return user.full_name or user.login


def _paid_line(user: User | None, paid_date: date | None) -> str:
    who = escape(_display_name(user)) if user else "—"
    return f"✅ Оплачено: {who}, {format_date(paid_date) if paid_date else '—'}"


def already_paid_text(paid_by: User | None, paid_date: date | None) -> str:
    who = _display_name(paid_by) if paid_by else "другой пользователь"
    return f"Уже оплачено: {who}, {format_date(paid_date) if paid_date else '—'}. Повторно оплачивать не нужно."


async def start(message: Message) -> None:
    await message.answer(START_TEXT)


async def link(message: Message, command: CommandObject, session_factory: SessionFactory) -> None:
    if message.chat.type != ChatType.PRIVATE:
        await message.answer(LINK_IN_PRIVATE)
        return
    code = (command.args or "").strip()
    if not code or message.from_user is None:
        await message.answer(LINK_USAGE)
        return
    async with session_factory() as session:
        outcome = await link_account(session, code, telegram_user_id=message.from_user.id, now=datetime.now(UTC))
    if outcome.result is LinkResult.LINKED and outcome.user is not None:
        await message.answer(
            f"Готово! Telegram привязан к учётной записи {_display_name(outcome.user)} ({outcome.user.login}). "
            "Теперь кнопка «✅ Оплачено» в напоминаниях отмечает оплату от вашего имени."
        )
    else:
        await message.answer(LINK_INVALID)


async def pay(
    callback: CallbackQuery,
    session_factory: SessionFactory,
    timezone: ZoneInfo,
    reminders: ReminderDispatcher | None = None,
) -> None:
    occurrence_id = parse_pay_callback(callback.data)
    if occurrence_id is None:
        await callback.answer(STALE_BUTTON, show_alert=True)
        return
    async with session_factory() as session:
        outcome = await mark_paid_from_telegram(
            session,
            occurrence_id,
            telegram_user_id=callback.from_user.id,
            today=today_in(timezone),
            now=datetime.now(UTC),
        )

    if outcome.result is PayResult.NOT_LINKED:
        await callback.answer(NOT_LINKED, show_alert=True)
        return
    if outcome.result is PayResult.NOT_FOUND:
        await callback.answer(NOT_FOUND, show_alert=True)
        return

    if outcome.result is PayResult.PAID:
        await callback.answer("Отмечено как оплаченное")
    else:
        # Нажали одновременно или по устаревшему сообщению: оплату второй раз не отмечаем.
        await callback.answer(already_paid_text(outcome.paid_by, outcome.paid_date), show_alert=True)
    message = callback.message
    if reminders is not None and isinstance(message, Message):
        # Все копии напоминания (общий чат и лички) становятся «✅ Платёж оплачен», включая это сообщение.
        await reminders.sync_telegram(occurrence_id, pressed=(message.chat.id, message.message_id))
        return
    # Без диспетчера (тесты): убираем кнопку и дописываем, кто оплатил, только в этом сообщении.
    if isinstance(message, Message) and message.html_text and "✅ Оплачено:" not in message.html_text:
        with contextlib.suppress(TelegramBadRequest):  # сообщение слишком старое или уже изменено
            await message.edit_text(
                f"{message.html_text}\n\n{_paid_line(outcome.paid_by, outcome.paid_date)}",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )


def build_router() -> Router:
    router = Router(name="invoice-keeper")
    router.message.register(start, CommandStart())
    router.message.register(link, Command("link"))
    router.callback_query.register(pay, F.data.startswith(PAY_CALLBACK_PREFIX))
    return router
