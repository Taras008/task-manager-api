from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.api.deps import get_session
from app.main import create_app


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_returns_503_when_database_is_down() -> None:
    app: FastAPI = create_app()
    broken_session = AsyncMock()
    broken_session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("down"))

    async def override() -> AsyncMock:
        return broken_session

    app.dependency_overrides[get_session] = override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


async def test_unknown_route_uses_unified_error_format(client: AsyncClient) -> None:
    response = await client.get("/nope")

    assert response.status_code == 404
    body = response.json()
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == "not_found"
