from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import clock
from tests.factories import auth_headers, create_task, create_user

TASKS = "/api/v1/tasks"


def future(days: int = 1) -> str:
    return (clock.now() + timedelta(days=days)).isoformat()


async def two_users(
    sf: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    a = await create_user(sf, "a@example.com")
    b = await create_user(sf, "b@example.com")
    return a.id, b.id


async def test_create_task(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author, assignee = await two_users(session_factory)
    fixed = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    deadline = fixed + timedelta(days=3)
    monkeypatch.setattr(clock, "now", lambda: fixed)

    r = await client.post(
        TASKS,
        headers=auth_headers(author),
        json={
            "title": "  Write docs ",
            "priority": "high",
            "assignee_id": assignee,
            "deadline": deadline.isoformat(),
        },
    )

    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Write docs"
    assert body["status"] == "backlog"
    assert body["priority"] == "high"
    assert body["author"]["id"] == author
    assert body["assignee"]["id"] == assignee
    assert body["created_at"].startswith("2026-05-01T10:00:00")
    assert body["updated_at"] == body["created_at"]


async def test_create_defaults(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    r = await client.post(
        TASKS, headers=auth_headers(author), json={"title": "T", "deadline": future()}
    )
    assert r.status_code == 201
    assert r.json()["priority"] == "medium"
    assert r.json()["assignee"] is None


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.post(TASKS, json={})).status_code == 401
    assert (await client.get(f"{TASKS}/1")).status_code == 401


async def test_get_task(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, other = await two_users(session_factory)
    task = await create_task(session_factory, author, assignee_id=other)

    r = await client.get(f"{TASKS}/{task.id}", headers=auth_headers(other))

    assert r.status_code == 200
    assert r.json()["id"] == task.id
    assert r.json()["assignee"]["id"] == other


async def test_get_does_not_n_plus_one(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    author, other = await two_users(session_factory)
    task = await create_task(session_factory, author, assignee_id=other)
    statements: list[str] = []

    def count(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        r = await client.get(f"{TASKS}/{task.id}", headers=auth_headers(author))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert r.status_code == 200
    # auth user + task + authors + assignees (selectinload)
    assert len(statements) <= 4


async def test_not_found(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    h = auth_headers(author)
    for r in (
        await client.get(f"{TASKS}/999", headers=h),
        await client.patch(f"{TASKS}/999", headers=h, json={"title": "x"}),
        await client.delete(f"{TASKS}/999", headers=h),
    ):
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


async def test_update_partial(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author, title="Old")
    later = clock.now() + timedelta(hours=1)
    monkeypatch.setattr(clock, "now", lambda: later)

    r = await client.patch(
        f"{TASKS}/{task.id}", headers=auth_headers(author), json={"title": "New", "priority": "low"}
    )

    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New"
    assert body["priority"] == "low"
    assert body["status"] == "backlog"
    assert datetime.fromisoformat(body["updated_at"]) == later
    assert datetime.fromisoformat(body["created_at"]) != later


async def test_update_unassign(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, other = await two_users(session_factory)
    task = await create_task(session_factory, author, assignee_id=other)

    r = await client.patch(
        f"{TASKS}/{task.id}", headers=auth_headers(author), json={"assignee_id": None}
    )

    assert r.status_code == 200
    assert r.json()["assignee"] is None


async def test_non_author_forbidden(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, other = await two_users(session_factory)
    task = await create_task(session_factory, author)
    h = auth_headers(other)

    patch = await client.patch(f"{TASKS}/{task.id}", headers=h, json={"title": "x"})
    delete = await client.delete(f"{TASKS}/{task.id}", headers=h)

    assert patch.status_code == 403
    assert delete.status_code == 403
    assert patch.json()["error"]["code"] == "permission_denied"


async def test_delete(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author)
    h = auth_headers(author)

    assert (await client.delete(f"{TASKS}/{task.id}", headers=h)).status_code == 204
    assert (await client.get(f"{TASKS}/{task.id}", headers=h)).status_code == 404


async def test_create_deadline_in_past(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    r = await client.post(
        TASKS, headers=auth_headers(author), json={"title": "T", "deadline": future(-1)}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_create_naive_deadline(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    r = await client.post(
        TASKS,
        headers=auth_headers(author),
        json={"title": "T", "deadline": "2099-01-01T10:00:00"},
    )
    assert r.status_code == 422


async def test_create_without_deadline(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    r = await client.post(TASKS, headers=auth_headers(author), json={"title": "T"})
    assert r.status_code == 422


async def test_create_unknown_assignee(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    r = await client.post(
        TASKS,
        headers=auth_headers(author),
        json={"title": "T", "deadline": future(), "assignee_id": 9999},
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"]["field"] == "assignee_id"


@pytest.mark.parametrize("body", [{"deadline": None}, {"title": None}, {"priority": None}])
async def test_update_null_required_field(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    body: dict[str, None],
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author)
    r = await client.patch(f"{TASKS}/{task.id}", headers=auth_headers(author), json=body)
    assert r.status_code == 422


async def test_update_rejects_status_field(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author)
    r = await client.patch(
        f"{TASKS}/{task.id}", headers=auth_headers(author), json={"status": "done"}
    )
    assert r.status_code == 422


async def test_update_deadline_in_past_and_naive(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author)
    h = auth_headers(author)
    past = await client.patch(f"{TASKS}/{task.id}", headers=h, json={"deadline": future(-1)})
    naive = await client.patch(
        f"{TASKS}/{task.id}", headers=h, json={"deadline": "2099-01-01T00:00:00"}
    )
    assert past.status_code == 422
    assert naive.status_code == 422


async def test_editing_other_fields_of_overdue_task_allowed(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author, deadline=clock.now() - timedelta(days=1))
    r = await client.patch(
        f"{TASKS}/{task.id}", headers=auth_headers(author), json={"title": "Renamed"}
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"


@pytest.mark.parametrize("value", [3, "urgent", None])
async def test_create_invalid_priority(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], value: object
) -> None:
    author, _ = await two_users(session_factory)
    r = await client.post(
        TASKS,
        headers=auth_headers(author),
        json={"title": "T", "deadline": future(), "priority": value},
    )
    assert r.status_code == 422


async def test_empty_patch_keeps_updated_at(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author, _ = await two_users(session_factory)
    task = await create_task(session_factory, author)
    monkeypatch.setattr(clock, "now", lambda: task.updated_at + timedelta(hours=1))

    r = await client.patch(f"{TASKS}/{task.id}", headers=auth_headers(author), json={})

    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["updated_at"]) == task.updated_at
