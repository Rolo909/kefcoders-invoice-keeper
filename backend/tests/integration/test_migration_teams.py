"""Миграция 0003 «команды» на базе, где уже есть данные без команд, — как на работающем сервере.

Отдельная база: миграции идут по-настоящему (с коммитами), общая тестовая база не затрагивается.
"""

import asyncio
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.services.occurrences import ensure_occurrences
from tests.conftest import ALEMBIC_INI, TEST_DATABASE_URL

DB_URL = make_url(TEST_DATABASE_URL).set(database="invoice_keeper_migration_test")


def _alembic(action: str, revision: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = DB_URL.render_as_string(hide_password=False)
    getattr(command, action)(config, revision)


async def _recreate_database() -> None:
    engine = create_async_engine(DB_URL.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_URL.database}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{DB_URL.database}"'))
    finally:
        await engine.dispose()


def sql(statement: str, **params: Any) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_async_engine(DB_URL, poolclass=pool.NullPool)
        try:
            async with engine.begin() as conn:
                rows: list[Any] = []
                for part in filter(str.strip, statement.split(";")):  # asyncpg — одна команда за вызов
                    result = await conn.execute(text(part), params)
                    rows = list(result) if result.returns_rows else []
                return rows
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def db_before_teams(migrated_db: None) -> Iterator[None]:
    asyncio.run(_recreate_database())
    _alembic("upgrade", "0002")
    yield


def _fill_old_data() -> None:
    """Данные версии без команд: админ, пользователь, платёж с двумя периодами (один оплачен), бюджет."""
    sql(
        """
        INSERT INTO users (id, login, password_hash, role, is_system) VALUES
            ('00000000-0000-0000-0000-00000000000a', 'admin', 'x', 'admin', true),
            ('00000000-0000-0000-0000-00000000000b', 'anna', 'x', 'user', false);
        INSERT INTO recurring_payments (id, name, amount, currency, period, first_due_date, created_by, created_at)
        VALUES ('00000000-0000-0000-0000-0000000000a1', 'Аренда офиса', 50000, 'RUB', 'monthly', '2026-01-25',
                '00000000-0000-0000-0000-00000000000a', '2026-01-10 12:00+03');
        INSERT INTO payment_occurrences
            (recurring_payment_id, seq, due_date, amount, currency, status, paid_date, paid_by) VALUES
            ('00000000-0000-0000-0000-0000000000a1', 0, '2026-01-25', 50000, 'RUB', 'paid', '2026-01-24',
             '00000000-0000-0000-0000-00000000000b'),
            ('00000000-0000-0000-0000-0000000000a1', 1, '2026-02-25', 50000, 'RUB', 'unpaid', NULL, NULL);
        INSERT INTO budgets (currency, period_type, year, month, amount) VALUES ('RUB', 'month', 2026, 1, 60000);
        """
    )


def test_existing_data_moves_to_one_team_and_old_payments_become_shared(db_before_teams: None) -> None:
    _fill_old_data()

    _alembic("upgrade", "head")

    [(team_id, name, joined)] = sql("SELECT id, name, created_at FROM teams")
    assert name == "Основная команда"
    assert sql("SELECT login, team_id FROM users ORDER BY login") == [("admin", None), ("anna", team_id)]
    assert sql("SELECT team_id FROM recurring_payments") == [(None,)]  # прежние платежи — общие
    assert sql("SELECT DISTINCT team_id FROM payment_occurrences") == [(team_id,)]
    assert sql("SELECT team_id FROM budgets") == [(team_id,)]
    [(payment_created,)] = sql("SELECT created_at FROM recurring_payments")
    assert joined <= payment_created  # команда «старше» платежа — его прошлые сроки остаются за ней
    assert sql("SELECT status, paid_date FROM payment_occurrences WHERE seq = 0") == [("paid", date(2026, 1, 24))]


def test_schedule_continues_after_migration_without_duplicates(db_before_teams: None) -> None:
    _fill_old_data()
    _alembic("upgrade", "head")

    async def continue_schedule() -> None:
        engine = create_async_engine(DB_URL, poolclass=pool.NullPool)
        try:
            async with AsyncSession(engine) as session:
                await ensure_occurrences(session, today=date(2026, 3, 1), horizon_days=60)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(continue_schedule())

    seqs = [seq for (seq,) in sql("SELECT seq FROM payment_occurrences ORDER BY seq")]
    assert seqs == [0, 1, 2, 3]  # старые периоды не задублированы, новые продолжают нумерацию


def test_empty_database_gets_no_teams(db_before_teams: None) -> None:
    _alembic("upgrade", "head")

    assert sql("SELECT count(*) FROM teams") == [(0,)]


def test_downgrade_keeps_data_while_there_is_one_team(db_before_teams: None) -> None:
    _fill_old_data()
    _alembic("upgrade", "head")

    _alembic("downgrade", "0002")

    assert sql("SELECT count(*) FROM payment_occurrences") == [(2,)]
    assert sql("SELECT login FROM users ORDER BY login") == [("admin",), ("anna",)]


def test_downgrade_is_refused_with_several_teams(db_before_teams: None) -> None:
    _fill_old_data()
    _alembic("upgrade", "head")
    sql("INSERT INTO teams (name) VALUES ('Студия дизайна')")

    with pytest.raises(RuntimeError, match="только пока команда одна"):
        _alembic("downgrade", "0002")
