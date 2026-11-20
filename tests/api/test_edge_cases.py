"""Крайні випадки, які раніше не були покриті тестами."""

import asyncio

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.factories import auth_headers, create_task, create_user

SessionFactory = async_sessionmaker[AsyncSession]


async def test_patch_unknown_assignee_is_422(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    user = await create_user(session_factory)
    task = await create_task(session_factory, user.id)
    r = await client.patch(
        f"/api/v1/tasks/{task.id}", headers=auth_headers(user.id), json={"assignee_id": 424242}
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"] == {"field": "assignee_id"}


async def test_valid_token_of_missing_user_is_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users/me", headers=auth_headers(424242))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_concurrent_register_same_email_yields_one_201_one_409(
    client: AsyncClient,
) -> None:
    payload = {"email": "race@example.com", "password": "Passw0rd!long"}
    results = await asyncio.gather(
        client.post("/api/v1/auth/register", json=payload),
        client.post("/api/v1/auth/register", json=payload),
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "email_already_registered"
