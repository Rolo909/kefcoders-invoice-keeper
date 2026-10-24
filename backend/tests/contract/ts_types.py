"""Минимальный разбор frontend/src/api/types.ts: какие поля и значения ждёт веб-панель."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

FRONTEND_API = Path(__file__).resolve().parents[3] / "frontend" / "src" / "api"
TYPES_TS = FRONTEND_API / "types.ts"
DATES_TS = FRONTEND_API.parent / "lib" / "dates.ts"

_INTERFACE = re.compile(r"export interface (\w+)(?:<[^>]*>)?(?: extends ([\w, ]+))? \{(.*?)\n\}", re.S)
_FIELD = re.compile(r"^\s*(\w+)(\?)?:", re.M)
_UNION = re.compile(r"export type (\w+) = ((?:'[^']*'\s*\|?\s*)+);")


@dataclass(frozen=True)
class Interface:
    required: frozenset[str]
    optional: frozenset[str]

    @property
    def fields(self) -> frozenset[str]:
        return self.required | self.optional


@cache
def interfaces() -> dict[str, Interface]:
    source = TYPES_TS.read_text(encoding="utf-8")
    raw = {name: (bases, body) for name, bases, body in _INTERFACE.findall(source)}

    @cache
    def resolve(name: str) -> Interface:
        bases, body = raw[name]
        required = {field for field, optional in _FIELD.findall(body) if not optional}
        optional = {field for field, opt in _FIELD.findall(body) if opt}
        for base in filter(None, (b.strip() for b in bases.split(","))):
            parent = resolve(base)
            required |= parent.required
            optional |= parent.optional
        return Interface(frozenset(required), frozenset(optional))

    return {name: resolve(name) for name in raw}


@cache
def unions() -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for path in (TYPES_TS, DATES_TS):
        for name, values in _UNION.findall(path.read_text(encoding="utf-8")):
            found[name] = frozenset(re.findall(r"'([^']*)'", values))
    return found
