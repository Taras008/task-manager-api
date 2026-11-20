from datetime import UTC, timedelta

from app.core import clock


def test_now_is_timezone_aware_utc() -> None:
    value = clock.now()

    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
    assert value.tzinfo is UTC
