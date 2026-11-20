from datetime import UTC, datetime


def now() -> datetime:
    """Єдине джерело поточного часу (timezone-aware UTC). У тестах мокається."""
    return datetime.now(UTC)
