import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus
from app.models.comment import Comment
from tests.factories import auth_headers, create_comment, create_task, create_user

SessionFactory = async_sessionmaker[AsyncSession]

TASKS = "/api/v1/tasks"
BASE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


def url(task_id: int) -> str:
    return f"{TASKS}/{task_id}/comments"


async def setup(sf: SessionFactory, **task_kw: Any) -> tuple[int, int]:
    user = await create_user(sf, "a@example.com")
    task = await create_task(sf, user.id, **task_kw)
    return user.id, task.id


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get(url(1))).status_code == 401
    assert (await client.post(url(1), json={"text": "x"})).status_code == 401


async def test_create_comment(
    client: AsyncClient, session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, task_id = await setup(session_factory)
    monkeypatch.setattr(clock, "now", lambda: BASE)
    r = await client.post(url(task_id), headers=auth_headers(user_id), json={"text": "  Hello  "})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["text"] == "Hello"
    assert body["task_id"] == task_id
    assert body["author"] == {"id": user_id, "email": "a@example.com"}
    assert datetime.fromisoformat(body["created_at"]) == BASE


@pytest.mark.parametrize("status", list(TaskStatus))
async def test_comment_allowed_in_any_status(
    client: AsyncClient, session_factory: SessionFactory, status: TaskStatus
) -> None:
    user_id, task_id = await setup(session_factory, status=status)
    r = await client.post(url(task_id), headers=auth_headers(user_id), json={"text": "ok"})
    assert r.status_code == 201


async def test_any_user_can_comment(client: AsyncClient, session_factory: SessionFactory) -> None:
    _, task_id = await setup(session_factory)
    other = await create_user(session_factory, "b@example.com")
    r = await client.post(url(task_id), headers=auth_headers(other.id), json={"text": "hi"})
    assert r.status_code == 201
    assert r.json()["author"]["id"] == other.id


async def test_list_comments_chronological_with_pagination(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    user_id, task_id = await setup(session_factory)
    other_task = await create_task(session_factory, user_id)
    for i in range(5):
        await create_comment(
            session_factory,
            task_id,
            user_id,
            text=f"c{i}",
            created_at=BASE + timedelta(minutes=10 - i),
        )
    await create_comment(session_factory, other_task.id, user_id, text="other")

    r = await client.get(url(task_id), headers=auth_headers(user_id), params={"page": 1, "size": 2})
    assert r.status_code == 200
    body = r.json()
    assert [c["text"] for c in body["items"]] == ["c4", "c3"]
    assert (body["total"], body["page"], body["size"], body["pages"]) == (5, 1, 2, 3)

    r = await client.get(url(task_id), headers=auth_headers(user_id), params={"page": 3, "size": 2})
    assert [c["text"] for c in r.json()["items"]] == ["c0"]


async def test_list_empty(client: AsyncClient, session_factory: SessionFactory) -> None:
    user_id, task_id = await setup(session_factory)
    r = await client.get(url(task_id), headers=auth_headers(user_id))
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20, "pages": 0}


async def test_unknown_task_returns_404(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    user = await create_user(session_factory)
    headers = auth_headers(user.id)
    r = await client.post(url(999), headers=headers, json={"text": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert (await client.get(url(999), headers=headers)).status_code == 404


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   "}, {}, {"text": "x" * 5001}])
async def test_invalid_text_returns_422(
    client: AsyncClient, session_factory: SessionFactory, payload: dict[str, Any]
) -> None:
    user_id, task_id = await setup(session_factory)
    r = await client.post(url(task_id), headers=auth_headers(user_id), json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_invalid_pagination_returns_422(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    user_id, task_id = await setup(session_factory)
    r = await client.get(url(task_id), headers=auth_headers(user_id), params={"size": 101})
    assert r.status_code == 422


async def test_deleting_task_cascades_to_comments(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    user_id, task_id = await setup(session_factory)
    await create_comment(session_factory, task_id, user_id)
    r = await client.delete(f"{TASKS}/{task_id}", headers=auth_headers(user_id))
    assert r.status_code == 204
    async with session_factory() as session:
        count = (await session.execute(select(func.count(Comment.id)))).scalar_one()
    assert count == 0


async def count_statements(
    engine: AsyncEngine, client: AsyncClient, user_id: int, task_id: int
) -> int:
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        r = await client.get(url(task_id), headers=auth_headers(user_id), params={"size": 50})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert r.status_code == 200
    return len(statements)


async def test_query_count_is_fixed(
    client: AsyncClient, session_factory: SessionFactory, engine: AsyncEngine
) -> None:
    user_id, task_id = await setup(session_factory)
    other = await create_user(session_factory, "b@example.com")
    await create_comment(session_factory, task_id, user_id)
    one = await count_statements(engine, client, user_id, task_id)

    for i in range(20):
        await create_comment(session_factory, task_id, user_id if i % 2 else other.id)
    many = await count_statements(engine, client, user_id, task_id)
    assert one == many


async def test_huge_page_returns_422(client: AsyncClient, session_factory: SessionFactory) -> None:
    user_id, task_id = await setup(session_factory)
    r = await client.get(
        url(task_id), headers=auth_headers(user_id), params={"page": 99999999999999999999}
    )
    assert r.status_code == 422


async def test_comment_vs_concurrent_task_delete_never_500(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    user_id, task_id = await setup(session_factory)
    headers = auth_headers(user_id)
    results = await asyncio.gather(
        client.post(url(task_id), headers=headers, json={"text": "x"}),
        client.delete(f"{TASKS}/{task_id}", headers=headers),
    )
    assert results[0].status_code in (201, 404)
    assert results[1].status_code == 204
