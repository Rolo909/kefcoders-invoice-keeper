import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

MONEY_PRECISION = 14
MONEY_SCALE = 2


def pg_enum[E: StrEnum](enum_cls: type[E], name: str) -> Enum:
    """Нативный enum PostgreSQL, хранящий значения (`monthly`), а не имена членов (`MONTHLY`)."""
    return Enum(enum_cls, name=name, values_callable=lambda members: [m.value for m in members])


class UuidPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"), sort_order=-1
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), sort_order=1)
