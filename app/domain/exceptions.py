from typing import Any


class DomainError(Exception):
    """Базовий доменний виняток. Сервіси не знають про HTTP, мапінг — у main.py."""

    code = "domain_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class NotFoundError(DomainError):
    code = "not_found"


class PermissionDeniedError(DomainError):
    code = "permission_denied"


class InvalidStatusTransitionError(DomainError):
    code = "invalid_status_transition"


class BusinessRuleViolationError(DomainError):
    code = "business_rule_violation"


class DomainValidationError(DomainError):
    """Не плутати з pydantic ValidationError (напр. дедлайн у минулому)."""

    code = "validation_error"
