from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Размер страницы")]
OffsetQuery = Annotated[int, Query(ge=0, description="Сколько записей пропустить")]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
