import os
import tempfile

# Окружение задаётся до импорта приложения: Settings читаются при импорте app.db.
# Тесты всегда работают с отдельной тестовой БД — рабочая база не затрагивается.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://invoice_keeper:change-me@127.0.0.1:5432/invoice_keeper_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="ik-uploads-")  # чеки тестов — во временной папке

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import SessionFactory, get_session
from app.domain.enums import NotificationChannel, Role
from app.main import create_app
from app.models import User
from app.security import hash_password
from app.services.notifiers.base import Reminder, SendResult
from app.services.reminders import ReminderDispatcher

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


# ---------- API поверх тестовой БД ----------

ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin-password-1"
USER_LOGIN = "anna"
USER_PASSWORD = "anna-password-1"


@pytest.fixture(scope="session")
def password_hashes() -> dict[str, str]:
    """argon2 медленный намеренно — считаем хеши один раз на прогон."""
    return {password: hash_password(password) for password in (ADMIN_PASSWORD, USER_PASSWORD)}


@pytest.fixture
async def admin(db_session: AsyncSession, password_hashes: dict[str, str]) -> User:
    user = User(login=ADMIN_LOGIN, password_hash=password_hashes[ADMIN_PASSWORD], role=Role.ADMIN, is_system=True)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def regular_user(db_session: AsyncSession, password_hashes: dict[str, str]) -> User:
    user = User(login=USER_LOGIN, password_hash=password_hashes[USER_PASSWORD], role=Role.USER, full_name="Анна")
    db_session.add(user)
    await db_session.flush()
    return user


class RecordingNotifier:
    """Вместо Telegram: запоминает отправленные напоминания, умеет имитировать сбой."""

    channel = NotificationChannel.TELEGRAM

    def __init__(self) -> None:
        self.sent: list[Reminder] = []
        self.failure: SendResult | None = None

    async def send(self, reminder: Reminder) -> SendResult:
        if self.failure is not None:
            return self.failure
        self.sent.append(reminder)
        return SendResult(ok=True, telegram_message_id=len(self.sent))

    async def check(self) -> SendResult:
        return self.failure or SendResult(ok=True)


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def session_factory(db_session: AsyncSession) -> SessionFactory:
    """Фабрика сессий для кода, который открывает сессию сам (worker, бот), — в транзакции теста."""

    @asynccontextmanager
    async def test_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    return test_session


@pytest.fixture
def reminders(session_factory: SessionFactory, notifier: RecordingNotifier) -> ReminderDispatcher:
    """Диспетчер напоминаний, работающий в транзакции теста."""
    return ReminderDispatcher(session_factory, [notifier], remind_days_before=3, timezone=ZoneInfo("Europe/Moscow"))


@pytest.fixture
async def api(app: FastAPI, db_session: AsyncSession, reminders: ReminderDispatcher) -> AsyncIterator[AsyncClient]:
    """Клиент API, все запросы которого идут в транзакцию теста (откатывается после теста)."""

    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override
    app.state.reminders = reminders
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def login(api: AsyncClient, login_name: str, password: str) -> str:
    response = await api.post("/api/v1/auth/login", json={"login": login_name, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
