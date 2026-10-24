"""Telegram-бот: /start, /link <код> и кнопка «✅ Оплачено» в напоминаниях.

Обработчики тонкие: вся логика — в app.services.telegram (её же проверяют тесты).
Зависимости session_factory и timezone приходят из данных Dispatcher (см. app.bot.runner).
"""

import contextlib
import logging
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
from app.services.telegram import (
    PAY_CALLBACK_PREFIX,
    LinkResult,
    PayResult,
    PressedIn,
    link_account,
    mark_paid_from_telegram,
    migrate_team_chats,
    parse_pay_callback,
)

START_TEXT = (
    "Я бот Invoice Keeper: напоминаю об оплате регулярных платежей за 3 дня до срока.\n\n"
    "Чтобы отмечать оплату кнопкой «✅ Оплачено», привяжите аккаунт: в панели откройте "
    "«Профиль» → Telegram → «Получить код» и пришлите мне в личном чате команду /link <код>.\n\n"
    "Оплату отмечают только участники команды этого платежа, добавленные в панели, — "
    "остальным кнопка откажет. ID группы для настройки команды покажет /chatid."
)
LINK_IN_PRIVATE = "Код привязки отправляйте в личном чате со мной — так его не увидят другие участники группы."
LINK_USAGE = "Пришлите код из панели: /link 123456"
LINK_INVALID = "Код не подошёл: он неверный, уже использован или истёк. Получите новый в панели: «Профиль» → Telegram."
NOT_LINKED = (
    "Ваш Telegram не привязан к панели. Откройте «Профиль» → Telegram и пришлите мне в личном чате /link <код>."
)
NOT_FOUND = "Этот период не найден — возможно, платёж прекращён."
WRONG_CHAT = "Эта кнопка из другого чата. Отметьте оплату в чате команды «{team}» или в панели."
NOT_MEMBER = "Отмечать оплату могут только участники команды «{team}». Обратитесь к администратору."
CHAT_ID_TEXT = (
    "ID этого чата: <code>{chat_id}</code>\n"
    "Вставьте его в панели: «Команды» → команда → «ID чата» — и напоминания команды будут приходить сюда."
)
STALE_BUTTON = "Кнопка устарела."

logger = logging.getLogger(__name__)


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


async def chat_id(message: Message) -> None:
    """ID чата для карточки команды: getUpdates недоступен, пока бот запущен."""
    await message.answer(CHAT_ID_TEXT.format(chat_id=message.chat.id), parse_mode=ParseMode.HTML)


async def chat_migrated(message: Message, session_factory: SessionFactory) -> None:
    """Группа стала супергруппой — у неё новый id; переносим его в команды."""
    if message.migrate_to_chat_id is None:
        return
    async with session_factory() as session:
        teams = await migrate_team_chats(session, message.chat.id, message.migrate_to_chat_id)
    if teams:
        logger.info("Чат %s стал %s: обновлены команды %s", message.chat.id, message.migrate_to_chat_id, teams)


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
    callback: CallbackQuery, session_factory: SessionFactory, timezone: ZoneInfo, fallback_chat_id: str | None
) -> None:
    occurrence_id = parse_pay_callback(callback.data)
    if occurrence_id is None:
        await callback.answer(STALE_BUTTON, show_alert=True)
        return
    chat = callback.message.chat if callback.message is not None else None
    async with session_factory() as session:
        outcome = await mark_paid_from_telegram(
            session,
            occurrence_id,
            telegram_user_id=callback.from_user.id,
            pressed_in=PressedIn(chat.id, chat.username) if chat is not None else None,
            fallback_chat_id=fallback_chat_id,
            today=today_in(timezone),
            now=datetime.now(UTC),
        )

    refusals = {
        PayResult.NOT_LINKED: NOT_LINKED,
        PayResult.NOT_FOUND: NOT_FOUND,
        PayResult.WRONG_CHAT: WRONG_CHAT.format(team=outcome.team_name),
        PayResult.NOT_MEMBER: NOT_MEMBER.format(team=outcome.team_name),
    }
    if outcome.result in refusals:
        # Отказ видит только нажавший; сообщение и кнопка остаются для участников команды.
        await callback.answer(refusals[outcome.result], show_alert=True)
        return

    if outcome.result is PayResult.PAID:
        await callback.answer("Отмечено как оплаченное")
    else:
        # Нажали одновременно или по устаревшему сообщению: оплату второй раз не отмечаем.
        await callback.answer(already_paid_text(outcome.paid_by, outcome.paid_date), show_alert=True)
    # Убираем кнопку и дописываем, кто оплатил, — чтобы весь чат видел, что вопрос закрыт.
    message = callback.message
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
    router.message.register(chat_id, Command("chatid"))
    router.message.register(chat_migrated, F.migrate_to_chat_id)
    router.callback_query.register(pay, F.data.startswith(PAY_CALLBACK_PREFIX))
    return router
