from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskPriority, TaskStatus
from tests.factories import auth_headers, create_task, create_user

STATS = "/api/v1/tasks/stats"
NOW = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now", lambda: NOW)


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get(STATS)).status_code == 401


async def test_empty_has_all_keys(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    r = await client.get(STATS, headers=auth_headers(u.id))
    assert r.status_code == 200
    assert r.json() == {
        "total": 0,
        "by_status": {
            "backlog": 0,
            "in_progress": 0,
            "review": 0,
            "done": 0,
            "cancelled": 0,
        },
        "by_priority": {"low": 0, "medium": 0, "high": 0},
        "overdue": 0,
        "active": 0,
    }


async def test_counts(client: AsyncClient, session_factory: SessionFactory) -> None:
    a = await create_user(session_factory, "a@example.com")
    b = await create_user(session_factory, "b@example.com")
    past, future = NOW - timedelta(days=1), NOW + timedelta(days=1)
    await create_task(session_factory, a.id, status=TaskStatus.BACKLOG, deadline=past)
    await create_task(
        session_factory,
        a.id,
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        deadline=future,
    )
    await create_task(
        session_factory, b.id, status=TaskStatus.REVIEW, priority=TaskPriority.LOW, deadline=past
    )
    await create_task(session_factory, b.id, status=TaskStatus.DONE, deadline=past)
    await create_task(session_factory, b.id, status=TaskStatus.CANCELLED, deadline=past)

    body = (await client.get(STATS, headers=auth_headers(a.id))).json()
    assert body["total"] == 5
    assert body["by_status"] == {
        "backlog": 1,
        "in_progress": 1,
        "review": 1,
        "done": 1,
        "cancelled": 1,
    }
    assert body["by_priority"] == {"low": 1, "medium": 3, "high": 1}
    assert body["active"] == 3
    assert body["overdue"] == 2  # backlog + review; done/cancelled не рахуються


async def test_overdue_follows_clock(
    client: AsyncClient, session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id, deadline=NOW + timedelta(hours=1))
    headers = auth_headers(u.id)
    assert (await client.get(STATS, headers=headers)).json()["overdue"] == 0

    later = NOW + timedelta(hours=2)
    monkeypatch.setattr(clock, "now", lambda: later)
    headers = auth_headers(u.id)  # новий токен: старий протермінувався б відносно мокнутого часу
    assert (await client.get(STATS, headers=headers)).json()["overdue"] == 1


async def test_single_query(
    client: AsyncClient, session_factory: SessionFactory, engine: AsyncEngine
) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id)
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        r = await client.get(STATS, headers=auth_headers(u.id))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert r.status_code == 200
    assert len(statements) == 2  # користувач (auth) + stats
