"""teams

Команды: у пользователей, периодов и бюджетов появляется команда, у платежа — команда или null (общий).
Уже работающая база переносится в «Основную команду»; прежние платежи становятся общими.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TEAM = "Основная команда"


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
    )
    op.create_index("uq_teams_name_lower", "teams", [sa.literal_column("lower(name)")], unique=True)

    for table in ("users", "recurring_payments", "payment_occurrences", "budgets"):
        op.add_column(table, sa.Column("team_id", sa.Uuid(), nullable=True))

    # Живые данные: всё, что уже есть, — в одну команду. Её «дата создания» не позже первого платежа,
    # иначе прежние общие платежи считались бы появившимися раньше команды и теряли бы старые сроки.
    op.execute(
        sa.text(
            """
            INSERT INTO teams (name, created_at)
            SELECT :name, LEAST(
                now(),
                COALESCE((SELECT min(created_at) FROM recurring_payments), now()),
                COALESCE((SELECT min(created_at) FROM users WHERE role = 'user'), now())
            )
            WHERE EXISTS (SELECT 1 FROM users WHERE role = 'user')
               OR EXISTS (SELECT 1 FROM payment_occurrences)
               OR EXISTS (SELECT 1 FROM budgets)
            """
        ).bindparams(name=DEFAULT_TEAM)
    )
    op.execute("UPDATE users SET team_id = (SELECT id FROM teams) WHERE role = 'user'")
    op.execute("UPDATE payment_occurrences SET team_id = (SELECT id FROM teams)")
    op.execute("UPDATE budgets SET team_id = (SELECT id FROM teams)")

    op.alter_column("payment_occurrences", "team_id", nullable=False)
    op.alter_column("budgets", "team_id", nullable=False)

    op.create_foreign_key(op.f("fk_users_team_id_teams"), "users", "teams", ["team_id"], ["id"], ondelete="RESTRICT")
    op.create_index(op.f("ix_users_team_id"), "users", ["team_id"], unique=False)
    op.create_check_constraint(op.f("ck_users_team_matches_role"), "users", "role = 'user' OR team_id IS NULL")

    op.create_foreign_key(
        op.f("fk_recurring_payments_team_id_teams"),
        "recurring_payments",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_recurring_payments_team_id"), "recurring_payments", ["team_id"], unique=False)

    op.create_foreign_key(
        op.f("fk_payment_occurrences_team_id_teams"),
        "payment_occurrences",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_payment_occurrences_recurring_payment_id_seq", "payment_occurrences", type_="unique")
    op.create_unique_constraint(
        op.f("uq_payment_occurrences_recurring_payment_id_team_id_seq"),
        "payment_occurrences",
        ["recurring_payment_id", "team_id", "seq"],
    )
    op.create_index(
        "ix_payment_occurrences_team_due_date", "payment_occurrences", ["team_id", "due_date"], unique=False
    )

    op.create_foreign_key(op.f("fk_budgets_team_id_teams"), "budgets", "teams", ["team_id"], ["id"], ondelete="CASCADE")
    op.drop_constraint("uq_budgets_currency_period_type_year_month", "budgets", type_="unique")
    op.create_unique_constraint(
        op.f("uq_budgets_team_id_currency_period_type_year_month"),
        "budgets",
        ["team_id", "currency", "period_type", "year", "month"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Без команд у периода снова один ключ (платёж, seq) — с двумя командами данные не уложить.
    teams = op.get_bind().scalar(sa.text("SELECT count(*) FROM teams"))
    if teams and teams > 1:
        raise RuntimeError("Откат 0003 возможен, только пока команда одна: удалите лишние команды")

    op.drop_constraint("uq_budgets_team_id_currency_period_type_year_month", "budgets", type_="unique")
    op.create_unique_constraint(
        op.f("uq_budgets_currency_period_type_year_month"),
        "budgets",
        ["currency", "period_type", "year", "month"],
        postgresql_nulls_not_distinct=True,
    )
    op.drop_constraint(op.f("fk_budgets_team_id_teams"), "budgets", type_="foreignkey")

    op.drop_index("ix_payment_occurrences_team_due_date", table_name="payment_occurrences")
    op.drop_constraint(
        op.f("uq_payment_occurrences_recurring_payment_id_team_id_seq"), "payment_occurrences", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_payment_occurrences_recurring_payment_id_seq"), "payment_occurrences", ["recurring_payment_id", "seq"]
    )
    op.drop_constraint(op.f("fk_payment_occurrences_team_id_teams"), "payment_occurrences", type_="foreignkey")

    op.drop_index(op.f("ix_recurring_payments_team_id"), table_name="recurring_payments")
    op.drop_constraint(op.f("fk_recurring_payments_team_id_teams"), "recurring_payments", type_="foreignkey")

    op.drop_constraint(op.f("ck_users_team_matches_role"), "users", type_="check")
    op.drop_index(op.f("ix_users_team_id"), table_name="users")
    op.drop_constraint(op.f("fk_users_team_id_teams"), "users", type_="foreignkey")

    for table in ("budgets", "payment_occurrences", "recurring_payments", "users"):
        op.drop_column(table, "team_id")
    op.drop_index("uq_teams_name_lower", table_name="teams")
    op.drop_table("teams")
