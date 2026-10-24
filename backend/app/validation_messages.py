"""Ошибки валидации запроса — понятным русским текстом, готовым к показу в панели.

Стандартный ответ FastAPI (список ошибок на английском с полем `input`) не подходит: панель
показывает `detail` как есть, а `input` вернул бы клиенту присланные данные, включая пароль.
"""

from collections.abc import Mapping, Sequence
from typing import Any

FIELD_LABELS = {
    "login": "Логин",
    "password": "Пароль",
    "full_name": "ФИО",
    "email": "Почта",
    "notify_email": "Напоминания на почту",
    "name": "Название",
    "description": "Описание",
    "amount": "Сумма",
    "currency": "Валюта",
    "period": "Периодичность",
    "next_due_date": "Дата ближайшей оплаты",
    "end_date": "Дата окончания",
    "status": "Статус",
    "paid_date": "Дата оплаты",
    "overdue": "Просрочка",
    "state": "Состояние",
    "date_from": "Начало периода",
    "date_to": "Конец периода",
    "as_of": "Дата итогов",
    "recurring_payment_id": "Платёж",
    "include_deleted": "Показать прекращённые",
    "sort": "Сортировка",
    "limit": "Размер страницы",
    "offset": "Сдвиг",
    "q": "Поиск",
    "month": "Месяц",
    "year": "Год",
    "period_type": "Тип бюджета",
    "action": "Действие",
    "actor_id": "Кто",
    "channel": "Канал",
    "attachment_id": "Идентификатор",
    "user_id": "Идентификатор",
    "payment_id": "Идентификатор",
    "occurrence_id": "Идентификатор",
}

_VALUE_ERROR_PREFIX = "Value error, "


def _field(loc: Sequence[Any]) -> str | None:
    """Имя поля из loc: ("body", "login") → "login"; ("query", "currency", 0) → "currency"."""
    names = [part for part in loc[1:] if isinstance(part, str)]
    return names[-1] if names else None


def _label(field: str | None) -> str:
    return FIELD_LABELS.get(field or "", field or "Запрос")


def _symbols(count: object) -> str:
    n = int(str(count))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} символа"  # «не короче 21 символа»
    return f"{n} символов"


def _expected(ctx: Mapping[str, Any]) -> str:
    return str(ctx.get("expected", "")).replace("'", "").replace(" or ", " или ")


def message_for(error: Mapping[str, Any]) -> str:
    kind = error.get("type", "")
    ctx: Mapping[str, Any] = error.get("ctx") or {}
    field = _field(error.get("loc", ()))
    label = _label(field)
    msg = str(error.get("msg", ""))

    if kind == "value_error" and msg.startswith(_VALUE_ERROR_PREFIX):
        return msg.removeprefix(_VALUE_ERROR_PREFIX)  # наши правила уже сформулированы по-русски
    if kind == "json_invalid":
        return "Некорректный JSON в теле запроса"
    if kind in {"model_attributes_type", "dict_type"} or (kind == "missing" and field is None):
        return "Тело запроса должно быть JSON-объектом"
    if kind == "string_too_short" and ctx.get("min_length") == 1:
        kind = "missing"  # пустая строка в обязательном поле — то же, что незаполненное поле
    templates = {
        "missing": f"Не заполнено поле «{label}»",
        "extra_forbidden": f"Поле «{field}» передавать нельзя",
        "enum": f"{label}: допустимые значения — {_expected(ctx)}",
        "literal_error": f"{label}: допустимые значения — {_expected(ctx)}",
        "string_type": f"{label}: нужна строка",
        "string_too_short": f"{label}: не короче {_symbols(ctx.get('min_length', 0))}",
        "string_too_long": f"{label}: не длиннее {_symbols(ctx.get('max_length', 0))}",
        "bool_parsing": f"{label}: true или false",
        "bool_type": f"{label}: true или false",
        "int_parsing": f"{label}: целое число",
        "int_type": f"{label}: целое число",
        "greater_than_equal": f"{label}: не меньше {ctx.get('ge')}",
        "less_than_equal": f"{label}: не больше {ctx.get('le')}",
        "decimal_parsing": f"{label}: число, например 1500.00",
        "decimal_type": f"{label}: число, например 1500.00",
        "date_parsing": f"{label}: дата в формате ГГГГ-ММ-ДД",
        "date_from_datetime_parsing": f"{label}: дата в формате ГГГГ-ММ-ДД",
        "date_type": f"{label}: дата в формате ГГГГ-ММ-ДД",
        "uuid_parsing": f"{label}: неверный идентификатор",
        "uuid_type": f"{label}: неверный идентификатор",
    }
    return templates.get(kind, f"{label}: {msg}")


def validation_detail(errors: Sequence[Mapping[str, Any]]) -> str:
    """Все ошибки одной строкой без повторов, в порядке появления."""
    return "; ".join(dict.fromkeys(message_for(error) for error in errors))
