from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus
from tests.factories import auth_headers, create_task, create_user

OVERDUE = "/api/v1/tasks/overdue"
NOW = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(clock, "now", lambda: NOW)
    return NOW


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get(OVERDUE)).status_code == 401


async def test_empty(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    r = await client.get(OVERDUE, headers=auth_headers(u.id))
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20, "pages": 0}


async def test_only_active_past_deadline(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    past = NOW - timedelta(days=1)
    expected = []
    for status in (TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.REVIEW):
        expected.append((await create_task(session_factory, u.id, status=status, deadline=past)).id)
    for status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        await create_task(session_factory, u.id, status=status, deadline=past)
    await create_task(session_factory, u.id, deadline=NOW + timedelta(days=1))
    await create_task(session_factory, u.id, deadline=NOW)  # межа: не прострочена

    r = await client.get(OVERDUE, headers=auth_headers(u.id))
    body = r.json()
    assert sorted(i["id"] for i in body["items"]) == sorted(expected)
    assert body["total"] == 3


async def test_ordered_by_deadline_and_paginated(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    ids = []
    for days in (3, 1, 2):  # створюємо не по порядку
        t = await create_task(session_factory, u.id, deadline=NOW - timedelta(days=days))
        ids.append((days, t.id))
    ordered = [i for _, i in sorted(ids, reverse=True)]  # більше днів = старіший дедлайн

    r = await client.get(OVERDUE, headers=auth_headers(u.id), params={"size": 2})
    body = r.json()
    assert [i["id"] for i in body["items"]] == ordered[:2]
    assert (body["total"], body["page"], body["size"], body["pages"]) == (3, 1, 2, 2)

    r = await client.get(OVERDUE, headers=auth_headers(u.id), params={"size": 2, "page": 2})
    assert [i["id"] for i in r.json()["items"]] == ordered[2:]


async def test_visible_to_non_author(client: AsyncClient, session_factory: SessionFactory) -> None:
    a = await create_user(session_factory, "a@example.com")
    b = await create_user(session_factory, "b@example.com")
    await create_task(session_factory, a.id, deadline=NOW - timedelta(hours=1))
    r = await client.get(OVERDUE, headers=auth_headers(b.id))
    assert r.json()["total"] == 1
