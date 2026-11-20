from datetime import datetime

from app.domain.exceptions import DomainValidationError


def validate_deadline_not_in_past(deadline: datetime, now: datetime) -> None:
    """Дедлайн не може бути меншим за поточний момент (рівність дозволена)."""
    if deadline < now:
        raise DomainValidationError(
            "Deadline must not be in the past", details={"field": "deadline"}
        )
