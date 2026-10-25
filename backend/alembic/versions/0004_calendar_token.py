"""calendar token

Секрет в ссылке подписки на календарь (.ics) — по нему Google, Outlook и Яндекс-календарь
получают сроки платежей без входа в панель.

Revision ID: 0004
Revises: 0003_tg
Create Date: 2026-10-25 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003_tg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("calendar_token", sa.String(length=64), nullable=True))
    op.create_unique_constraint(op.f("uq_users_calendar_token"), "users", ["calendar_token"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_calendar_token"), "users", type_="unique")
    op.drop_column("users", "calendar_token")
