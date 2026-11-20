from datetime import UTC, datetime, timedelta

import pytest

from app.domain.exceptions import DomainValidationError
from app.domain.rules import validate_deadline_not_in_past

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_past_deadline_rejected() -> None:
    with pytest.raises(DomainValidationError):
        validate_deadline_not_in_past(NOW - timedelta(seconds=1), NOW)


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(days=1)])
def test_now_and_future_deadline_allowed(delta: timedelta) -> None:
    validate_deadline_not_in_past(NOW + delta, NOW)
