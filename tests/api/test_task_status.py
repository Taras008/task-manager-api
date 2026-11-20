from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus as S
from tests.factories import auth_headers, create_task, create_user

TASKS = "/api/v1/tasks"


def future(days: int = 1) -> str:
    return (clock.now() + timedelta(days=days)).isoformat()


async def users(sf: async_sessionmaker[AsyncSession]) -> tuple[int, int, int]:
    a = await create_user(sf, "a@example.com")
    b = await create_user(sf, "b@example.com")
    c = await create_user(sf, "c@example.com")
    return a.id, b.id, c.id


async def set_status(client: AsyncClient, user: int, task: int, status: str):  # type: ignore[no-untyped-def]
    return await client.patch(
        f"{TASKS}/{task}/status", headers=auth_headers(user), json={"status": status}
    )


# --- Переходи ---


async def test_happy_path_to_done(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b)
    for status in ("in_progress", "review", "done"):
        r = await set_status(client, a, t.id, status)
        assert r.status_code == 200
        assert r.json()["status"] == status


async def test_updated_at_set_on_status_change(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b)
    later = clock.now() + timedelta(hours=1)
    monkeypatch.setattr(clock, "now", lambda: later)
    r = await set_status(client, a, t.id, "in_progress")
    assert datetime.fromisoformat(r.json()["updated_at"]) == later


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.BACKLOG, S.REVIEW),
        (S.BACKLOG, S.DONE),
        (S.IN_PROGRESS, S.BACKLOG),
        (S.IN_PROGRESS, S.DONE),
        (S.REVIEW, S.IN_PROGRESS),
        (S.REVIEW, S.CANCELLED),
        (S.DONE, S.IN_PROGRESS),
        (S.DONE, S.CANCELLED),
        (S.CANCELLED, S.BACKLOG),
        (S.BACKLOG, S.BACKLOG),
    ],
)
async def test_invalid_transition_409(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    current: S,
    target: S,
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=current)
    r = await set_status(client, a, t.id, target.value)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_status_transition"


async def test_in_progress_requires_assignee(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, _, _ = await users(session_factory)
    t = await create_task(session_factory, a)
    r = await set_status(client, a, t.id, "in_progress")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "business_rule_violation"


async def test_done_requires_assignee(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, _, _ = await users(session_factory)
    t = await create_task(session_factory, a, status=S.REVIEW)  # без виконавця
    r = await set_status(client, a, t.id, "done")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "business_rule_violation"


async def test_done_with_expired_deadline_409(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=S.REVIEW)
    later = clock.now() + timedelta(days=2)  # дедлайн задачі = +1 день
    monkeypatch.setattr(clock, "now", lambda: later)
    r = await set_status(client, a, t.id, "done")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "business_rule_violation"


async def test_done_before_deadline_ok(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=S.REVIEW)
    assert (await set_status(client, a, t.id, "done")).status_code == 200


# --- Права, помилки входу ---


async def test_assignee_can_change_status(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b)
    assert (await set_status(client, b, t.id, "in_progress")).status_code == 200


async def test_stranger_403(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, c = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b)
    r = await set_status(client, c, t.id, "in_progress")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "permission_denied"


async def test_status_unknown_task_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, _, _ = await users(session_factory)
    assert (await set_status(client, a, 999, "in_progress")).status_code == 404


async def test_status_requires_auth(client: AsyncClient) -> None:
    r = await client.patch(f"{TASKS}/1/status", json={"status": "in_progress"})
    assert r.status_code == 401


async def test_invalid_status_value_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, _, _ = await users(session_factory)
    t = await create_task(session_factory, a)
    r = await set_status(client, a, t.id, "bogus")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_status_not_editable_via_patch(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, _, _ = await users(session_factory)
    t = await create_task(session_factory, a)
    r = await client.patch(f"{TASKS}/{t.id}", headers=auth_headers(a), json={"status": "done"})
    assert r.status_code == 422


# --- Read-only, виконавець, видалення ---


@pytest.mark.parametrize("status", [S.DONE, S.CANCELLED])
async def test_terminal_task_read_only(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], status: S
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=status)
    r = await client.patch(f"{TASKS}/{t.id}", headers=auth_headers(a), json={"title": "New"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "business_rule_violation"


@pytest.mark.parametrize("status", [S.REVIEW, S.DONE])
async def test_assignee_change_forbidden_in_review_done(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], status: S
) -> None:
    a, b, c = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=status)
    r = await client.patch(f"{TASKS}/{t.id}", headers=auth_headers(a), json={"assignee_id": c})
    assert r.status_code == 409


async def test_review_other_fields_still_editable(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=S.REVIEW)
    r = await client.patch(f"{TASKS}/{t.id}", headers=auth_headers(a), json={"title": "New"})
    assert r.status_code == 200


async def test_assignee_change_in_progress_allowed(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, c = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=S.IN_PROGRESS)
    r = await client.patch(f"{TASKS}/{t.id}", headers=auth_headers(a), json={"assignee_id": c})
    assert r.status_code == 200
    assert r.json()["assignee"]["id"] == c


@pytest.mark.parametrize("status", [S.IN_PROGRESS, S.REVIEW])
async def test_delete_forbidden(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], status: S
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=status)
    r = await client.delete(f"{TASKS}/{t.id}", headers=auth_headers(a))
    assert r.status_code == 409


@pytest.mark.parametrize("status", [S.BACKLOG, S.DONE, S.CANCELLED])
async def test_delete_allowed(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], status: S
) -> None:
    a, b, _ = await users(session_factory)
    t = await create_task(session_factory, a, assignee_id=b, status=status)
    r = await client.delete(f"{TASKS}/{t.id}", headers=auth_headers(a))
    assert r.status_code == 204


# --- Ліміт активних задач ---


async def fill_active(
    sf: async_sessionmaker[AsyncSession], author: int, assignee: int, n: int
) -> None:
    statuses = [S.BACKLOG, S.IN_PROGRESS, S.REVIEW]
    for i in range(n):
        await create_task(sf, author, assignee_id=assignee, status=statuses[i % 3])


async def test_limit_on_create(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    await fill_active(session_factory, a, b, 9)
    body = {"title": "T", "assignee_id": b, "deadline": future()}
    assert (await client.post(TASKS, headers=auth_headers(a), json=body)).status_code == 201
    r = await client.post(TASKS, headers=auth_headers(a), json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "business_rule_violation"


async def test_terminal_tasks_not_counted(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    await fill_active(session_factory, a, b, 9)
    for status in (S.DONE, S.CANCELLED):
        await create_task(session_factory, a, assignee_id=b, status=status)
    body = {"title": "T", "assignee_id": b, "deadline": future()}
    assert (await client.post(TASKS, headers=auth_headers(a), json=body)).status_code == 201


async def test_limit_on_assignee_change(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, c = await users(session_factory)
    await fill_active(session_factory, a, b, 10)
    t = await create_task(session_factory, a, assignee_id=c)
    r = await client.patch(f"{TASKS}/{t.id}", headers=auth_headers(a), json={"assignee_id": b})
    assert r.status_code == 409


async def test_limit_not_rechecked_for_same_assignee(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    await fill_active(session_factory, a, b, 10)
    t = await create_task(session_factory, a, assignee_id=b, status=S.BACKLOG)  # 11-та в БД
    r = await client.patch(
        f"{TASKS}/{t.id}", headers=auth_headers(a), json={"assignee_id": b, "title": "X"}
    )
    assert r.status_code == 200


async def test_status_change_not_blocked_by_limit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b, _ = await users(session_factory)
    await fill_active(session_factory, a, b, 9)
    t = await create_task(session_factory, a, assignee_id=b)  # рівно 10
    assert (await set_status(client, a, t.id, "in_progress")).status_code == 200
