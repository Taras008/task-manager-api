import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.domain.enums import TaskStatus
from app.models.task import Task
from app.workers import overdue
from app.workers.heartbeat import is_fresh, write_heartbeat
from app.workers.overdue import OVERDUE_LOCK_KEY, run_forever, run_once
from tests.factories import auth_headers, create_task, create_user
from tests.notifier import RecordingNotifier

NOW = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(days=1)
LATER = NOW + timedelta(days=1)

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(clock, "now", lambda: NOW)
    return NOW


def exists(path: str | Path) -> bool:
    return Path(path).exists()


async def get_task(sf: SessionFactory, task_id: int) -> Task:
    async with sf() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


@pytest.mark.parametrize("status", [TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.REVIEW])
async def test_cancels_overdue_active(
    session_factory: SessionFactory, notifier: RecordingNotifier, status: TaskStatus
) -> None:
    u = await create_user(session_factory)
    t = await create_task(
        session_factory, u.id, status=status, deadline=PAST, updated_at=PAST, created_at=PAST
    )
    assert await run_once(session_factory, notifier) == 1
    task = await get_task(session_factory, t.id)
    assert task.status is TaskStatus.CANCELLED
    assert task.updated_at == NOW


@pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
async def test_ignores_terminal(
    session_factory: SessionFactory, notifier: RecordingNotifier, status: TaskStatus
) -> None:
    u = await create_user(session_factory)
    t = await create_task(session_factory, u.id, status=status, deadline=PAST, updated_at=PAST)
    assert await run_once(session_factory, notifier) == 0
    task = await get_task(session_factory, t.id)
    assert task.status is status
    assert task.updated_at == PAST


async def test_ignores_not_overdue_including_boundary(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    u = await create_user(session_factory)
    future = await create_task(session_factory, u.id, deadline=LATER)
    boundary = await create_task(session_factory, u.id, deadline=NOW)  # deadline == now
    assert await run_once(session_factory, notifier) == 0
    assert (await get_task(session_factory, future.id)).status is TaskStatus.BACKLOG
    assert (await get_task(session_factory, boundary.id)).status is TaskStatus.BACKLOG


async def test_second_run_is_noop(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id, deadline=PAST)
    await create_task(session_factory, u.id, deadline=PAST)
    assert await run_once(session_factory, notifier) == 2
    assert await run_once(session_factory, notifier) == 0


async def test_skips_when_lock_held(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    u = await create_user(session_factory)
    t = await create_task(session_factory, u.id, deadline=PAST)
    async with session_factory() as holder, holder.begin():
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": OVERDUE_LOCK_KEY})
        assert await run_once(session_factory, notifier) == 0
        assert (await get_task(session_factory, t.id)).status is TaskStatus.BACKLOG
    assert await run_once(session_factory, notifier) == 1


async def test_overdue_endpoint_empty_after_tick(
    client: AsyncClient, session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id, deadline=PAST)
    headers = auth_headers(u.id)
    assert (await client.get("/api/v1/tasks/overdue", headers=headers)).json()["total"] == 1
    await run_once(session_factory, notifier)
    assert (await client.get("/api/v1/tasks/overdue", headers=headers)).json()["total"] == 0


# --- нотифікації автоскасування ---


async def test_notifies_assignees_of_cancelled_tasks(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    with_assignee = await create_task(
        session_factory, author.id, assignee_id=assignee.id, deadline=PAST
    )
    await create_task(session_factory, author.id, deadline=PAST)  # без виконавця
    assert await run_once(session_factory, notifier) == 2
    assert notifier.calls == [("auto_cancelled", with_assignee.id, assignee.id)]


async def test_no_notifications_for_untouched_tasks(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    for status, deadline in (
        (TaskStatus.DONE, PAST),
        (TaskStatus.CANCELLED, PAST),
        (TaskStatus.BACKLOG, LATER),
    ):
        await create_task(
            session_factory, author.id, assignee_id=assignee.id, status=status, deadline=deadline
        )
    assert await run_once(session_factory, notifier) == 0
    assert notifier.calls == []


async def test_no_notifications_when_lock_held(
    session_factory: SessionFactory, notifier: RecordingNotifier
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    await create_task(session_factory, author.id, assignee_id=assignee.id, deadline=PAST)
    async with session_factory() as holder, holder.begin():
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": OVERDUE_LOCK_KEY})
        await run_once(session_factory, notifier)
    assert notifier.calls == []


async def test_notifier_failure_does_not_break_tick(
    session_factory: SessionFactory, caplog: pytest.LogCaptureFixture
) -> None:
    author = await create_user(session_factory, email="a@example.com")
    assignee = await create_user(session_factory, email="b@example.com")
    first = await create_task(session_factory, author.id, assignee_id=assignee.id, deadline=PAST)
    second = await create_task(session_factory, author.id, assignee_id=assignee.id, deadline=PAST)
    notifier = RecordingNotifier(fail_for={first.id})
    with caplog.at_level(logging.ERROR):
        assert await run_once(session_factory, notifier) == 2
    # Скасування збережено, другу нотифікацію не заблоковано збоєм першої.
    assert (await get_task(session_factory, first.id)).status is TaskStatus.CANCELLED
    assert notifier.calls == [("auto_cancelled", second.id, assignee.id)]
    assert "Failed to notify" in caplog.text


# --- структуровані логи ---


async def test_tick_log_has_cancelled_and_duration(
    session_factory: SessionFactory, notifier: RecordingNotifier, caplog: pytest.LogCaptureFixture
) -> None:
    u = await create_user(session_factory)
    await create_task(session_factory, u.id, deadline=PAST)
    with caplog.at_level(logging.INFO, logger="app.workers.overdue"):
        await run_once(session_factory, notifier)
    record = next(r for r in caplog.records if getattr(r, "event", None) == "overdue_tick")
    assert record.cancelled == 1  # type: ignore[attr-defined]
    assert isinstance(record.duration_ms, int)  # type: ignore[attr-defined]


async def test_lock_not_acquired_is_logged_separately(
    session_factory: SessionFactory, notifier: RecordingNotifier, caplog: pytest.LogCaptureFixture
) -> None:
    async with session_factory() as holder, holder.begin():
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": OVERDUE_LOCK_KEY})
        with caplog.at_level(logging.INFO, logger="app.workers.overdue"):
            await run_once(session_factory, notifier)
    events = [getattr(r, "event", None) for r in caplog.records]
    assert "lock_not_acquired" in events
    assert "overdue_tick" not in events


# --- heartbeat і graceful shutdown ---


def test_heartbeat_freshness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = str(tmp_path / "hb")
    assert not is_fresh(path, 180)  # файлу немає
    write_heartbeat(path)
    assert is_fresh(path, 180)
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(seconds=181))
    assert not is_fresh(path, 180)


async def test_run_forever_writes_heartbeat_after_tick(
    session_factory: SessionFactory, notifier: RecordingNotifier, tmp_path: Path
) -> None:
    path = str(tmp_path / "hb")
    stop = asyncio.Event()
    task = asyncio.create_task(run_forever(session_factory, notifier, 60, stop, path))
    for _ in range(100):
        if exists(path):
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert exists(path)


async def test_failed_tick_does_not_refresh_heartbeat(
    session_factory: SessionFactory,
    notifier: RecordingNotifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_: object) -> int:
        raise RuntimeError("db down")

    monkeypatch.setattr(overdue, "run_once", boom)
    path = tmp_path / "hb"
    stop = asyncio.Event()
    task = asyncio.create_task(run_forever(session_factory, notifier, 60, stop, str(path)))
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert not exists(path)


async def test_stop_waits_for_current_tick_to_finish(
    session_factory: SessionFactory,
    notifier: RecordingNotifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    in_tick = asyncio.Event()
    finished: list[bool] = []

    async def slow_tick(*_: object) -> int:
        in_tick.set()
        await asyncio.sleep(0.3)  # «SIGTERM» приходить посеред тіку
        finished.append(True)
        return 0

    monkeypatch.setattr(overdue, "run_once", slow_tick)
    path = tmp_path / "hb"
    task = asyncio.create_task(run_forever(session_factory, notifier, 60, stop, str(path)))
    await in_tick.wait()
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert finished == [True]  # тік не обірвано
    assert exists(path)  # heartbeat записано після нього


async def test_logging_notifier_message_contains_ids(caplog: pytest.LogCaptureFixture) -> None:
    from app.services.notifier import LoggingNotifier

    with caplog.at_level(logging.INFO, logger="app.services.notifier"):
        await LoggingNotifier().notify_task_auto_cancelled(42, 7)
    assert "task_id=42" in caplog.text
    assert "assignee_id=7" in caplog.text


async def test_hung_tick_times_out_and_loop_continues(
    session_factory: SessionFactory,
    notifier: RecordingNotifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def hang(*_: object) -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(3600)
        return 0

    monkeypatch.setattr(overdue, "run_once", hang)
    path = tmp_path / "hb"
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_forever(session_factory, notifier, 0.05, stop, str(path), tick_timeout=0.05)
    )
    await asyncio.sleep(0.5)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert calls >= 2  # після таймауту цикл продовжив
    assert not exists(path)  # heartbeat не оновлювався
