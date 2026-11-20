"""Heartbeat воркера: mtime файлу оновлюється після кожного успішного тіку."""

import os
import sys
from pathlib import Path

from app.core import clock
from app.core.config import get_settings

HEALTHCHECK_INTERVALS = 3


def write_heartbeat(path: str) -> None:
    ts = clock.now().timestamp()
    file = Path(path)
    file.touch()
    os.utime(file, (ts, ts))


def is_fresh(path: str, max_age_seconds: float) -> bool:
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return False
    return clock.now().timestamp() - mtime <= max_age_seconds


def main() -> int:
    """Entrypoint для healthcheck у compose: 0 — здоровий, 1 — heartbeat відсутній/застарів."""
    settings = get_settings()
    max_age = HEALTHCHECK_INTERVALS * settings.overdue_interval_seconds
    return 0 if is_fresh(settings.scheduler_heartbeat_path, max_age) else 1


if __name__ == "__main__":
    sys.exit(main())
