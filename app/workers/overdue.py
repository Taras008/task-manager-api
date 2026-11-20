"""Періодичне автоскасування прострочених задач (окремий процес `scheduler`)."""

import asyncio
import contextlib
import logging
import signal
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.domain.events import TaskAutoCancelled
from app.repositories.task import TaskRepository
from app.services.notifier import LoggingNotifier, Notifier
from app.workers.heartbeat import write_heartbeat

logger = logging.getLogger(__name__)

# Довільна стала bigint-константа; ідентифікує lock воркера автоскасування.
OVERDUE_LOCK_KEY = 7_340_001
# Верхня межа одного тіку: завислий коннект не має блокувати воркер назавжди.
DEFAULT_TICK_TIMEOUT_SECONDS = 30.0


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


async def _notify_assignees(notifier: Notifier, cancelled: list[TaskAutoCancelled]) -> None:
    """Нотифікації після commit. Збій однієї не ламає тік і не блокує решту."""
    for event in cancelled:
        if event.assignee_id is None:
            continue
        try:
            await notifier.notify_task_auto_cancelled(event.task_id, event.assignee_id)
        except Exception:
            logger.exception(
                "Failed to notify about auto-cancelled task",
                extra={"task_id": event.task_id, "assignee_id": event.assignee_id},
            )


async def run_once(session_factory: async_sessionmaker[AsyncSession], notifier: Notifier) -> int:
    """Один тік: скасовує прострочені задачі. Повертає кількість (0, якщо lock зайнятий).

    `pg_try_advisory_xact_lock` живе рівно в цій транзакції й знімається на commit/rollback.
    """
    started = time.perf_counter()
    async with session_factory() as session, session.begin():
        acquired = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": OVERDUE_LOCK_KEY}
            )
        ).scalar_one()
        if not acquired:
            duration_ms = _elapsed_ms(started)
            logger.info(
                "Overdue tick: lock_not_acquired duration_ms=%d",
                duration_ms,
                extra={"event": "lock_not_acquired", "duration_ms": duration_ms},
            )
            return 0
        cancelled = await TaskRepository(session).cancel_overdue(clock.now())
    duration_ms = _elapsed_ms(started)
    logger.info(
        "Overdue tick: cancelled=%d duration_ms=%d",
        len(cancelled),
        duration_ms,
        extra={"event": "overdue_tick", "cancelled": len(cancelled), "duration_ms": duration_ms},
    )
    await _notify_assignees(notifier, cancelled)
    return len(cancelled)


async def run_forever(
    session_factory: async_sessionmaker[AsyncSession],
    notifier: Notifier,
    interval: float,
    stop: asyncio.Event,
    heartbeat_path: str,
    tick_timeout: float = DEFAULT_TICK_TIMEOUT_SECONDS,
) -> None:
    """Цикл тіків. `stop` перевіряється лише між тіками, тож поточний тік завжди добігає кінця."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(run_once(session_factory, notifier), timeout=tick_timeout)
            write_heartbeat(heartbeat_path)
        except Exception:
            # Heartbeat не оновлюємо: збійний тік має призвести до unhealthy.
            # TimeoutError теж потрапляє сюди: транзакцію скасовано, наступний тік спробує знову.
            logger.exception("Overdue worker iteration failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)


async def main() -> None:
    configure_logging()
    settings = get_settings()
    engine = create_engine()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logger.info("Overdue worker started, interval=%ss", settings.overdue_interval_seconds)
    try:
        await run_forever(
            create_session_factory(engine),
            LoggingNotifier(),
            settings.overdue_interval_seconds,
            stop,
            settings.scheduler_heartbeat_path,
        )
    finally:
        await engine.dispose()
        logger.info("Overdue worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
