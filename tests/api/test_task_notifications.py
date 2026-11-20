from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus
from app.main import create_app
from tests.factories import auth_headers, create_task, create_user
from tests.notifier import RecordingNotifier

TASKS = "/api/v1/tasks"
NOW = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
DEADLINE = (NOW + timedelta(days=1)).isoformat()

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(clock, "now", lambda: NOW)
    return NOW


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
async def nclient(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> AsyncIterator[AsyncClient]:
    app = create_app(session_factory, notifier=notifier)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_create_with_assignee_notifies(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    r = await nclient.post(
        TASKS,
        json={"title": "T", "deadline": DEADLINE, "assignee_id": assignee.id},
        headers=auth_headers(author.id),
    )
    assert r.status_code == 201
    assert notifier.calls == [("assigned", r.json()["id"], assignee.id)]


async def test_create_without_assignee_does_not_notify(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory)
    r = await nclient.post(
        TASKS, json={"title": "T", "deadline": DEADLINE}, headers=auth_headers(author.id)
    )
    assert r.status_code == 201
    assert notifier.calls == []


async def test_patch_assignee_change_notifies_only_on_change(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    task = await create_task(session_factory, author.id)
    headers = auth_headers(author.id)

    r = await nclient.patch(f"{TASKS}/{task.id}", json={"title": "New"}, headers=headers)
    assert r.status_code == 200
    assert notifier.calls == []

    r = await nclient.patch(
        f"{TASKS}/{task.id}", json={"assignee_id": assignee.id}, headers=headers
    )
    assert r.status_code == 200
    assert notifier.calls == [("assigned", task.id, assignee.id)]

    r = await nclient.patch(
        f"{TASKS}/{task.id}", json={"assignee_id": assignee.id}, headers=headers
    )
    assert r.status_code == 200
    assert len(notifier.calls) == 1


async def test_status_change_notifies_assignee(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    task = await create_task(session_factory, author.id, assignee_id=assignee.id)
    r = await nclient.patch(
        f"{TASKS}/{task.id}/status",
        json={"status": "in_progress"},
        headers=auth_headers(author.id),
    )
    assert r.status_code == 200
    assert notifier.calls == [
        ("status", task.id, assignee.id, TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS)
    ]


async def test_assignee_own_status_change_does_not_notify_self(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    task = await create_task(session_factory, author.id, assignee_id=assignee.id)
    r = await nclient.patch(
        f"{TASKS}/{task.id}/status",
        json={"status": "in_progress"},
        headers=auth_headers(assignee.id),
    )
    assert r.status_code == 200
    assert notifier.calls == []


async def test_failed_requests_do_not_notify(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    task = await create_task(session_factory, author.id, assignee_id=assignee.id)
    # Недозволений перехід → 409.
    r = await nclient.patch(
        f"{TASKS}/{task.id}/status", json={"status": "done"}, headers=auth_headers(author.id)
    )
    assert r.status_code == 409
    # Не автор редагує → 403.
    r = await nclient.patch(
        f"{TASKS}/{task.id}", json={"assignee_id": author.id}, headers=auth_headers(assignee.id)
    )
    assert r.status_code == 403
    assert notifier.calls == []


async def test_events_do_not_leak_between_sequential_requests(
    nclient: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    """TaskService створюється на кожен запит, тож events попереднього запиту не повторюються."""
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    headers = auth_headers(author.id)

    first = await nclient.post(
        TASKS,
        json={"title": "T1", "deadline": DEADLINE, "assignee_id": assignee.id},
        headers=headers,
    )
    assert notifier.calls == [("assigned", first.json()["id"], assignee.id)]

    # Другий запит без подій не має повторити нотифікацію першого.
    second = await nclient.post(TASKS, json={"title": "T2", "deadline": DEADLINE}, headers=headers)
    assert second.status_code == 201
    assert len(notifier.calls) == 1

    # Третій запит із власною подією додає рівно одну нотифікацію.
    r = await nclient.patch(
        f"{TASKS}/{second.json()['id']}", json={"assignee_id": assignee.id}, headers=headers
    )
    assert r.status_code == 200
    assert notifier.calls == [
        ("assigned", first.json()["id"], assignee.id),
        ("assigned", second.json()["id"], assignee.id),
    ]
