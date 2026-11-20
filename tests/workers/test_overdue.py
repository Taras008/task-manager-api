from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus
from app.models.task import Task
from app.workers.overdue import OVERDUE_LOCK_KEY, run_once
from tests.factories import auth_headers, create_task, create_user

NOW = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(days=1)
LATER = NOW + timedelta(days=1)

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(clock, "now", lambda: NOW)
    return NOW


async def get_task(sf: SessionFactory, task_id: int) -> Task:
    async with sf() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


@pytest.mark.parametrize("status", [TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.REVIEW])
async def test_cancels_overdue_active(session_factory: SessionFactory, status: TaskStatus) -> None:
    u = await create_user(session_factory)
    t = await create_task(
        session_factory, u.id, status=status, deadline=PAST, updated_at=PAST, created_at=PAST
    )
    assert await run_once(session_factory) == 1
    task = await get_task(session_factory, t.id)
    assert task.status is TaskStatus.CANCELLED
    assert task.updated_at == NOW


@pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
async def test_ignores_terminal(session_factory: SessionFactory, status: TaskStatus) -> None:
    u = await create_user(session_factory)
    t = await create_task(session_factory, u.id, status=status, deadline=PAST, updated_at=PAST)
    assert await run_once(session_factory) == 0
    task = await get_task(session_factory, t.id)
    assert task.status is status
    assert task.updated_at == PAST


async def test_ignores_not_overdue_including_boundary(session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    future = await create_task(session_factory, u.id, deadline=LATER)
    boundary = await create_task(session_factory, u.id, deadline=NOW)  # deadline == now
    assert await run_once(session_factory) == 0
    assert (await get_task(session_factory, future.id)).status is TaskStatus.BACKLOG
    assert (await get_task(session_factory, boundary.id)).status is TaskStatus.BACKLOG


async def test_second_run_is_noop(session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id, deadline=PAST)
    await create_task(session_factory, u.id, deadline=PAST)
    assert await run_once(session_factory) == 2
    assert await run_once(session_factory) == 0


async def test_skips_when_lock_held(session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    t = await create_task(session_factory, u.id, deadline=PAST)
    async with session_factory() as holder, holder.begin():
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": OVERDUE_LOCK_KEY})
        assert await run_once(session_factory) == 0
        assert (await get_task(session_factory, t.id)).status is TaskStatus.BACKLOG
    assert await run_once(session_factory) == 1


async def test_overdue_endpoint_empty_after_tick(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id, deadline=PAST)
    headers = auth_headers(u.id)
    assert (await client.get("/api/v1/tasks/overdue", headers=headers)).json()["total"] == 1
    await run_once(session_factory)
    assert (await client.get("/api/v1/tasks/overdue", headers=headers)).json()["total"] == 0
