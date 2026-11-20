"""Конкурентність і порядок помилок на рівні сервісу (реальні коміти, окремі сесії)."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus as S
from app.domain.exceptions import (
    BusinessRuleViolationError,
    DomainError,
    InvalidStatusTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task import TaskService
from tests.factories import create_task, create_user

SF = async_sessionmaker[AsyncSession]


async def run[T](sf: SF, call):  # type: ignore[no-untyped-def]
    async with sf() as session:
        return await call(TaskService(session))


async def count_assigned(sf: SF, user_id: int) -> int:
    async with sf() as session:
        result = await session.execute(
            select(func.count()).select_from(Task).where(Task.assignee_id == user_id)
        )
        return result.scalar_one()


async def test_concurrent_create_respects_limit(session_factory: SF) -> None:
    a = await create_user(session_factory, "a@example.com")
    b = await create_user(session_factory, "b@example.com")
    for _ in range(9):
        await create_task(session_factory, a.id, assignee_id=b.id)
    deadline = clock.now() + timedelta(days=1)

    async def create() -> object:
        data = TaskCreate(title="T", assignee_id=b.id, deadline=deadline)
        return await run(session_factory, lambda s: s.create(a, data))

    results = await asyncio.gather(create(), create(), return_exceptions=True)

    errors = [r for r in results if isinstance(r, BusinessRuleViolationError)]
    assert len(errors) == 1
    assert await count_assigned(session_factory, b.id) == 10


async def test_concurrent_reassign_respects_limit(session_factory: SF) -> None:
    a = await create_user(session_factory, "a@example.com")
    b = await create_user(session_factory, "b@example.com")
    c = await create_user(session_factory, "c@example.com")
    for _ in range(9):
        await create_task(session_factory, a.id, assignee_id=b.id)
    t1 = await create_task(session_factory, a.id, assignee_id=c.id)
    t2 = await create_task(session_factory, a.id, assignee_id=c.id)

    async def reassign(task_id: int) -> object:
        data = TaskUpdate(assignee_id=b.id)
        return await run(session_factory, lambda s: s.update(a, task_id, data))

    results = await asyncio.gather(reassign(t1.id), reassign(t2.id), return_exceptions=True)

    assert sum(isinstance(r, BusinessRuleViolationError) for r in results) == 1
    assert await count_assigned(session_factory, b.id) == 10


async def test_concurrent_status_changes_serialized(session_factory: SF) -> None:
    a = await create_user(session_factory, "a@example.com")
    b = await create_user(session_factory, "b@example.com")
    t = await create_task(session_factory, a.id, assignee_id=b.id, status=S.IN_PROGRESS)

    async def change(target: S) -> object:
        return await run(session_factory, lambda s: s.change_status(a, t.id, target))

    results = await asyncio.gather(change(S.REVIEW), change(S.CANCELLED), return_exceptions=True)

    failures = [r for r in results if isinstance(r, DomainError)]
    assert len(failures) == 1
    assert isinstance(failures[0], InvalidStatusTransitionError)


async def test_service_error_order(session_factory: SF) -> None:
    a = await create_user(session_factory, "a@example.com")
    b = await create_user(session_factory, "b@example.com")
    c = await create_user(session_factory, "c@example.com")
    done = await create_task(session_factory, a.id, assignee_id=b.id, status=S.DONE)

    async def as_user(user: User, task_id: int, target: S) -> object:
        return await run(session_factory, lambda s: s.change_status(user, task_id, target))

    with pytest.raises(NotFoundError):
        await as_user(a, 999, S.CANCELLED)
    with pytest.raises(PermissionDeniedError):
        await as_user(c, done.id, S.CANCELLED)
    with pytest.raises(InvalidStatusTransitionError):
        await as_user(a, done.id, S.CANCELLED)
