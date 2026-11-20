"""Періодичне автоскасування прострочених задач (окремий процес `scheduler`)."""

import asyncio
import contextlib
import logging
import signal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.repositories.task import TaskRepository

logger = logging.getLogger(__name__)

# Довільна стала bigint-константа; ідентифікує lock воркера автоскасування.
OVERDUE_LOCK_KEY = 7_340_001


async def run_once(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Один тік: скасовує прострочені задачі. Повертає кількість (0, якщо lock зайнятий).

    `pg_try_advisory_xact_lock` живе рівно в цій транзакції й знімається на commit/rollback.
    """
    async with session_factory() as session, session.begin():
        acquired = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": OVERDUE_LOCK_KEY}
            )
        ).scalar_one()
        if not acquired:
            logger.info("Overdue worker: lock is held by another instance, skipping")
            return 0
        cancelled = await TaskRepository(session).cancel_overdue(clock.now())
    if cancelled:
        logger.info("Overdue worker: cancelled %d task(s)", cancelled)
    return cancelled


async def run_forever(
    session_factory: async_sessionmaker[AsyncSession],
    interval: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await run_once(session_factory)
        except Exception:
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
        await run_forever(create_session_factory(engine), settings.overdue_interval_seconds, stop)
    finally:
        await engine.dispose()
        logger.info("Overdue worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
