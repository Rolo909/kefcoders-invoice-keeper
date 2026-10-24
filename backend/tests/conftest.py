import os

# Окружение задаётся до импорта приложения: Settings читаются при импорте app.db.
# Тесты всегда работают с отдельной тестовой БД — рабочая база не затрагивается.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://invoice_keeper:change-me@127.0.0.1:5432/invoice_keeper_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.main import create_app

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def _create_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database})
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[None]:
    """Тестовая БД, пересозданная миграциями: каждый прогон заодно проверяет downgrade/upgrade."""
    try:
        asyncio.run(_create_test_database())
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"PostgreSQL недоступен ({exc}). Запустите: docker compose up -d db")
    config = Config(str(ALEMBIC_INI))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def db_session(migrated_db: None) -> AsyncIterator[AsyncSession]:
    """Сессия внутри внешней транзакции, которая откатывается после теста."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
