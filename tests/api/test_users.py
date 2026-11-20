from datetime import timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.user import User
from tests.factories import auth_headers, create_user

ME = "/api/v1/users/me"


async def test_me_with_token(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_user(session_factory)

    response = await client.get(ME, headers=auth_headers(user.id))

    assert response.status_code == 200
    assert response.json()["id"] == user.id
    assert response.json()["email"] == user.email


async def test_me_without_token_is_401_in_unified_format(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_with_expired_token(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(session_factory)
    token = create_access_token(str(user.id), expires_delta=timedelta(minutes=5))
    real_now = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real_now + timedelta(minutes=10))

    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_me_with_garbage_token(client: AsyncClient) -> None:
    response = await client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401


async def test_me_for_deleted_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

    response = await client.get(ME, headers=auth_headers(user.id))

    assert response.status_code == 401


@pytest.mark.parametrize("exp", ["tomorrow", 1e20])
async def test_me_with_invalid_exp_is_401_not_500(client: AsyncClient, exp: object) -> None:
    settings = get_settings()
    token = jwt.encode(
        {"sub": "1", "exp": exp}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )

    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
