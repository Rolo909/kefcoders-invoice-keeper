"""Выгрузка OpenAPI-спецификации в docs/openapi.yaml — обязательный артефакт кейса.

Запуск из папки backend: `python -m app.scripts.export_openapi` (путь можно передать аргументом).
Тест tests/contract/test_openapi_file.py следит, чтобы файл не отставал от кода.
"""

import os
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.yaml"


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None  # многострочные описания — читаемым блоком
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def render(schema: dict[str, Any]) -> str:
    return yaml.dump(schema, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)


def main() -> None:
    # Для построения схемы база не нужна, но настройки обязательны — подставляем безопасные заглушки.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://openapi:openapi@localhost/openapi")
    os.environ.setdefault("ADMIN_PASSWORD", "openapi-export")
    from app.main import create_app

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(create_app().openapi()), encoding="utf-8", newline="\n")
    print(f"OpenAPI-спецификация сохранена: {target}")


if __name__ == "__main__":
    main()
