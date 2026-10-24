"""Тексты напоминаний на русском: суммы с пробелами между разрядами, даты ДД.ММ.ГГГГ, склонения."""

from datetime import date
from decimal import Decimal
from html import escape

from app.domain.enums import NotificationKind
from app.services.notifiers.base import Reminder


def plural_days(count: int) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        return f"{count} дней"
    word = {1: "день", 2: "дня", 3: "дня", 4: "дня"}.get(count % 10, "дней")
    return f"{count} {word}"


def format_money(amount: Decimal) -> str:
    """50000.5 → «50 000,50» (неразрывные пробелы, чтобы сумма не переносилась)."""
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def format_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _when(due: date, today: date) -> str:
    days_left = (due - today).days
    if days_left == 0:
        return "сегодня"
    if days_left == 1:
        return "завтра"
    return f"через {plural_days(days_left)}"


def paid_text_html(
    *, payment_name: str, amount: Decimal, currency: str, due_date: date, payer: str, paid_date: date
) -> str:
    """Чем заменяется напоминание после оплаты — в панели или кнопкой в Telegram."""
    return (
        f"✅ Платёж оплачен\n<b>{escape(payment_name)}</b>\nСумма: {format_money(amount)} {currency}\n"
        f"Срок оплаты: {format_date(due_date)}\nОплатил(а): {escape(payer)}, {format_date(paid_date)}"
    )


def reminder_text_html(reminder: Reminder) -> str:
    name = escape(reminder.payment_name)
    money = f"{format_money(reminder.amount)} {reminder.currency.value}"
    due = format_date(reminder.due_date)
    if reminder.kind is NotificationKind.OVERDUE:
        late = plural_days((reminder.today - reminder.due_date).days)
        return f"⚠️ Просрочена оплата\n<b>{name}</b>\nСумма: {money}\nСрок оплаты был: {due} (просрочено на {late})"
    when = _when(reminder.due_date, reminder.today)
    return f"🔔 Напоминание об оплате\n<b>{name}</b>\nСумма: {money}\nСрок оплаты: {due} ({when})"
