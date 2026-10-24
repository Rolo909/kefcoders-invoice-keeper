from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from app.db import get_session


class _HealthySession:
    async def execute(self, *_: Any) -> None:
        return None


class _BrokenSession:
    async def execute(self, *_: Any) -> None:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError())


def _use_session(app: FastAPI, session: object) -> None:
    async def override() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_session] = override


async def test_health_reports_ok_when_database_answers(app: FastAPI, client: AsyncClient) -> None:
    _use_session(app, _HealthySession())

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


async def test_health_reports_503_when_database_is_down(app: FastAPI, client: AsyncClient) -> None:
    _use_session(app, _BrokenSession())

    response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


async def test_swagger_ui_is_served_under_api_prefix(client: AsyncClient) -> None:
    response = await client.get("/api/v1/docs")

    assert response.status_code == 200
    assert "/api/v1/openapi.json" in response.text


async def test_openapi_schema_lists_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
