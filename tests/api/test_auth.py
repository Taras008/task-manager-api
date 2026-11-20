import threading
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from tests.factories import DEFAULT_PASSWORD, create_user

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"


async def test_register_returns_user_without_password(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER, json={"email": "New@Example.com", "password": "password123"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["id"] > 0
    assert body["created_at"]
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_duplicate_email_conflict(client: AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": "password123"}
    await client.post(REGISTER, json=payload)

    response = await client.post(REGISTER, json={**payload, "email": "DUP@example.com"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


async def test_register_validation(client: AsyncClient) -> None:
    short = await client.post(REGISTER, json={"email": "a@example.com", "password": "short"})
    bad_email = await client.post(REGISTER, json={"email": "nope", "password": "password123"})

    assert short.status_code == 422
    assert bad_email.status_code == 422
    assert short.json()["error"]["code"] == "validation_error"


async def test_login_success(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_user(session_factory, "login@example.com")

    response = await client.post(
        LOGIN, data={"username": "Login@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


async def test_login_wrong_password_and_unknown_email_look_the_same(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_user(session_factory, "login@example.com")

    wrong = await client.post(LOGIN, data={"username": "login@example.com", "password": "bad-pass"})
    unknown = await client.post(LOGIN, data={"username": "x@example.com", "password": "bad-pass"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.headers["www-authenticate"] == "Bearer"


async def test_register_login_me_flow(client: AsyncClient) -> None:
    await client.post(REGISTER, json={"email": "flow@example.com", "password": "password123"})
    login = await client.post(
        LOGIN, data={"username": "flow@example.com", "password": "password123"}
    )

    me = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )

    assert me.status_code == 200
    assert me.json()["email"] == "flow@example.com"


async def test_password_hashing_runs_off_event_loop(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import auth as auth_service

    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def spy(name: str, func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any) -> Any:
            seen[name] = threading.get_ident()
            return func(*args)

        return wrapper

    for name in ("hash_password", "verify_password", "verify_dummy_password"):
        monkeypatch.setattr(auth_service, name, spy(name, getattr(auth_service, name)))

    await client.post(REGISTER, json={"email": "t@example.com", "password": "password123"})
    await client.post(LOGIN, data={"username": "t@example.com", "password": "password123"})
    await client.post(LOGIN, data={"username": "none@example.com", "password": "password123"})

    assert set(seen) == {"hash_password", "verify_password", "verify_dummy_password"}
    assert all(thread != loop_thread for thread in seen.values())


async def test_login_with_corrupted_stored_hash_is_401(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_user(session_factory, "broken@example.com")
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == user.id).values(hashed_password="junk"))
        await session.commit()

    response = await client.post(
        LOGIN, data={"username": "broken@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
