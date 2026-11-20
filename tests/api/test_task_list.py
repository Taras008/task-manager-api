from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.enums import TaskPriority, TaskStatus
from tests.factories import auth_headers, create_task, create_user

TASKS = "/api/v1/tasks"
BASE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)

SessionFactory = async_sessionmaker[AsyncSession]


def day(n: int) -> datetime:
    return BASE + timedelta(days=n)


async def fetch(client: AsyncClient, user_id: int, **params: Any) -> dict[str, Any]:
    r = await client.get(TASKS, headers=auth_headers(user_id), params=params)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["items"]]


async def make(sf: SessionFactory, author: int, **kw: Any) -> int:
    return (await create_task(sf, author, **kw)).id


async def test_requires_auth(client: AsyncClient) -> None:
    r = await client.get(TASKS)
    assert r.status_code == 401
    assert r.json()["error"]["code"]


async def test_empty(client: AsyncClient, session_factory: SessionFactory) -> None:
    user = await create_user(session_factory)
    body = await fetch(client, user.id)
    assert body == {"items": [], "total": 0, "page": 1, "size": 20, "pages": 0}


async def test_item_shape(client: AsyncClient, session_factory: SessionFactory) -> None:
    author = await create_user(session_factory, "a@example.com")
    other = await create_user(session_factory, "b@example.com")
    await make(session_factory, author.id, assignee_id=other.id, priority=TaskPriority.HIGH)
    item = (await fetch(client, author.id))["items"][0]
    assert item["priority"] == "high"
    assert item["author"]["id"] == author.id
    assert item["assignee"]["id"] == other.id


async def test_filter_status(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    a = await make(session_factory, u.id, status=TaskStatus.BACKLOG)
    await make(session_factory, u.id, status=TaskStatus.DONE)
    body = await fetch(client, u.id, status="backlog")
    assert ids(body) == [a]
    assert body["total"] == 1


async def test_filter_priority(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    await make(session_factory, u.id, priority=TaskPriority.LOW)
    h = await make(session_factory, u.id, priority=TaskPriority.HIGH)
    assert ids(await fetch(client, u.id, priority="high")) == [h]


async def test_filter_assignee(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory, "a@example.com")
    v = await create_user(session_factory, "b@example.com")
    await make(session_factory, u.id)
    t = await make(session_factory, u.id, assignee_id=v.id)
    assert ids(await fetch(client, u.id, assignee_id=v.id)) == [t]


async def test_filter_deadline_bounds_are_inclusive(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    before = await make(session_factory, u.id, deadline=day(1))
    low = await make(session_factory, u.id, deadline=day(2))
    mid = await make(session_factory, u.id, deadline=day(3))
    high = await make(session_factory, u.id, deadline=day(4))
    after = await make(session_factory, u.id, deadline=day(5))

    both = await fetch(
        client,
        u.id,
        deadline_from=day(2).isoformat(),
        deadline_to=day(4).isoformat(),
        sort_by="deadline",
    )
    assert ids(both) == [low, mid, high]
    assert ids(await fetch(client, u.id, deadline_from=day(4).isoformat(), sort_by="deadline")) == [
        high,
        after,
    ]
    assert ids(await fetch(client, u.id, deadline_to=day(2).isoformat(), sort_by="deadline")) == [
        before,
        low,
    ]


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("report", ["Quarterly REPORT"]),  # регістр
        ("deploy", ["Fix bug"]),  # збіг в description
        ("100%", ["100% done"]),
        ("%", ["100% done"]),  # % не wildcard
        ("_", ["a_b"]),  # _ не wildcard
        ("a_b", ["a_b"]),
        ("\\", ["back\\slash"]),
        ("nothing-matches", []),
    ],
)
async def test_search(
    client: AsyncClient, session_factory: SessionFactory, term: str, expected: list[str]
) -> None:
    u = await create_user(session_factory)
    await make(session_factory, u.id, title="Quarterly REPORT")
    await make(session_factory, u.id, title="Fix bug", description="needs Deploy tomorrow")
    await make(session_factory, u.id, title="100% done")
    await make(session_factory, u.id, title="a_b")
    await make(session_factory, u.id, title="axb")
    await make(session_factory, u.id, title="back\\slash")
    body = await fetch(client, u.id, search=term)
    assert sorted(i["title"] for i in body["items"]) == sorted(expected)
    assert body["total"] == len(expected)


async def test_blank_search_is_ignored(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    await make(session_factory, u.id)
    assert (await fetch(client, u.id, search="   "))["total"] == 1


async def test_combined_filters(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory, "a@example.com")
    v = await create_user(session_factory, "b@example.com")
    hit = await make(
        session_factory,
        u.id,
        title="Release notes",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        assignee_id=v.id,
        deadline=day(3),
    )
    # кожна з цих задач порушує рівно одну умову
    await make(
        session_factory,
        u.id,
        title="Other",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        assignee_id=v.id,
        deadline=day(3),
    )
    await make(
        session_factory,
        u.id,
        title="Release notes",
        status=TaskStatus.BACKLOG,
        priority=TaskPriority.HIGH,
        assignee_id=v.id,
        deadline=day(3),
    )
    await make(
        session_factory,
        u.id,
        title="Release notes",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.LOW,
        assignee_id=v.id,
        deadline=day(3),
    )
    await make(
        session_factory,
        u.id,
        title="Release notes",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        assignee_id=u.id,
        deadline=day(3),
    )
    await make(
        session_factory,
        u.id,
        title="Release notes",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        assignee_id=v.id,
        deadline=day(9),
    )
    body = await fetch(
        client,
        u.id,
        search="release",
        status="in_progress",
        priority="high",
        assignee_id=v.id,
        deadline_from=day(1).isoformat(),
        deadline_to=day(5).isoformat(),
    )
    assert ids(body) == [hit]
    assert body["total"] == 1


async def test_default_sort(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    low = await make(session_factory, u.id, priority=TaskPriority.LOW, deadline=day(1))
    h_late = await make(session_factory, u.id, priority=TaskPriority.HIGH, deadline=day(5))
    h_early = await make(session_factory, u.id, priority=TaskPriority.HIGH, deadline=day(2))
    # однаковий пріоритет і дедлайн → за id
    tie_a = await make(session_factory, u.id, priority=TaskPriority.MEDIUM, deadline=day(3))
    tie_b = await make(session_factory, u.id, priority=TaskPriority.MEDIUM, deadline=day(3))
    assert ids(await fetch(client, u.id)) == [h_early, h_late, tie_a, tie_b, low]


async def test_sort_by_priority(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    lo = await make(session_factory, u.id, priority=TaskPriority.LOW)
    hi = await make(session_factory, u.id, priority=TaskPriority.HIGH)
    me = await make(session_factory, u.id, priority=TaskPriority.MEDIUM)
    me2 = await make(session_factory, u.id, priority=TaskPriority.MEDIUM)
    assert ids(await fetch(client, u.id, sort_by="priority", order="asc")) == [lo, me, me2, hi]
    assert ids(await fetch(client, u.id, sort_by="priority", order="desc")) == [hi, me, me2, lo]


async def test_sort_by_deadline(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    c = await make(session_factory, u.id, deadline=day(3))
    a = await make(session_factory, u.id, deadline=day(1))
    b = await make(session_factory, u.id, deadline=day(2))
    assert ids(await fetch(client, u.id, sort_by="deadline", order="asc")) == [a, b, c]
    assert ids(await fetch(client, u.id, sort_by="deadline", order="desc")) == [c, b, a]


async def test_sort_by_created_at(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    newest = await make(session_factory, u.id, created_at=day(-1))
    oldest = await make(session_factory, u.id, created_at=day(-3))
    middle = await make(session_factory, u.id, created_at=day(-2))
    assert ids(await fetch(client, u.id, sort_by="created_at", order="asc")) == [
        oldest,
        middle,
        newest,
    ]
    assert ids(await fetch(client, u.id, sort_by="created_at", order="desc")) == [
        newest,
        middle,
        oldest,
    ]


async def test_order_without_sort_by_keeps_default_sort(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    lo = await make(session_factory, u.id, priority=TaskPriority.LOW)
    hi = await make(session_factory, u.id, priority=TaskPriority.HIGH)
    assert ids(await fetch(client, u.id, order="asc")) == [hi, lo]


async def test_pagination(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    created = [await make(session_factory, u.id, deadline=day(i)) for i in range(1, 8)]

    p1 = await fetch(client, u.id, page=1, size=3, sort_by="deadline")
    p2 = await fetch(client, u.id, page=2, size=3, sort_by="deadline")
    p3 = await fetch(client, u.id, page=3, size=3, sort_by="deadline")
    assert (p1["total"], p1["pages"], p1["page"], p1["size"]) == (7, 3, 1, 3)
    assert ids(p1) == created[0:3]
    assert ids(p2) == created[3:6]
    assert ids(p3) == created[6:]  # остання неповна сторінка


async def test_pages_exact_multiple(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    for _ in range(4):
        await make(session_factory, u.id)
    body = await fetch(client, u.id, size=2)
    assert (body["total"], body["pages"]) == (4, 2)


async def test_page_out_of_range_is_empty(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    await make(session_factory, u.id)
    body = await fetch(client, u.id, page=5, size=10)
    assert body["items"] == []
    assert (body["total"], body["pages"], body["page"]) == (1, 1, 5)


async def test_total_respects_filters(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    for _ in range(3):
        await make(session_factory, u.id, status=TaskStatus.REVIEW)
    await make(session_factory, u.id)
    body = await fetch(client, u.id, status="review", size=2)
    assert (body["total"], body["pages"], len(body["items"])) == (3, 2, 2)


async def test_max_page_size(client: AsyncClient, session_factory: SessionFactory) -> None:
    u = await create_user(session_factory)
    assert (await fetch(client, u.id, size=100))["size"] == 100


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"size": 0},
        {"size": 101},
        {"page": "x"},
        {"status": "unknown"},
        {"priority": "urgent"},
        {"priority": "2"},
        {"sort_by": "title"},
        {"order": "sideways"},
        {"assignee_id": "abc"},
        {"deadline_from": "2030-01-01T00:00:00"},  # naive
        {"deadline_to": "2030-01-01"},
        {"deadline_from": "2030-01-03T00:00:00+00:00", "deadline_to": "2030-01-02T00:00:00+00:00"},
        {"search": "x" * 201},
    ],
)
async def test_invalid_params(
    client: AsyncClient, session_factory: SessionFactory, params: dict[str, Any]
) -> None:
    u = await create_user(session_factory)
    r = await client.get(TASKS, headers=auth_headers(u.id), params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_list_route_does_not_shadow_task_by_id(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    u = await create_user(session_factory)
    t = await make(session_factory, u.id)
    r = await client.get(f"{TASKS}/{t}", headers=auth_headers(u.id))
    assert r.status_code == 200


async def count_statements(engine: AsyncEngine, client: AsyncClient, user_id: int) -> int:
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        r = await client.get(TASKS, headers=auth_headers(user_id), params={"size": 50})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert r.status_code == 200
    return len(statements)


async def test_query_count_is_fixed(
    client: AsyncClient, session_factory: SessionFactory, engine: AsyncEngine
) -> None:
    u = await create_user(session_factory, "a@example.com")
    v = await create_user(session_factory, "b@example.com")
    await make(session_factory, u.id, assignee_id=v.id)
    one = await count_statements(engine, client, u.id)

    for i in range(30):
        await make(session_factory, u.id if i % 2 else v.id, assignee_id=v.id if i % 3 else None)
    many = await count_statements(engine, client, u.id)

    # auth user + count + select + selectinload автора + selectinload виконавця
    assert one == many == 5
