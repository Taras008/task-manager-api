from datetime import datetime

from app.domain.enums import TaskStatus
from app.domain.exceptions import (
    BusinessRuleViolationError,
    DomainValidationError,
    InvalidStatusTransitionError,
)
from app.domain.transitions import TERMINAL_STATUSES, is_transition_allowed

MAX_ACTIVE_TASKS = 10


def validate_deadline_not_in_past(deadline: datetime, now: datetime) -> None:
    """Дедлайн не може бути меншим за поточний момент (рівність дозволена)."""
    if deadline < now:
        raise DomainValidationError(
            "Deadline must not be in the past", details={"field": "deadline"}
        )


def ensure_transition_allowed(current: TaskStatus, target: TaskStatus) -> None:
    if not is_transition_allowed(current, target):
        raise InvalidStatusTransitionError(
            f"Transition from {current.value} to {target.value} is not allowed",
            details={"from": current.value, "to": target.value},
        )


def ensure_can_enter_status(
    target: TaskStatus, assignee_id: int | None, deadline: datetime, now: datetime
) -> None:
    """→ in_progress/done потребують виконавця; → done заборонено після дедлайну."""
    if target in (TaskStatus.IN_PROGRESS, TaskStatus.DONE) and assignee_id is None:
        raise BusinessRuleViolationError(
            f"Task cannot move to {target.value} without an assignee",
            details={"field": "assignee_id"},
        )
    if target is TaskStatus.DONE and deadline < now:
        raise BusinessRuleViolationError(
            "Task cannot be completed after its deadline", details={"field": "deadline"}
        )


def ensure_task_editable(status: TaskStatus) -> None:
    if status in TERMINAL_STATUSES:
        raise BusinessRuleViolationError(
            f"A {status.value} task is read-only", details={"status": status.value}
        )


def ensure_assignee_change_allowed(status: TaskStatus) -> None:
    if status in (TaskStatus.REVIEW, TaskStatus.DONE):
        raise BusinessRuleViolationError(
            f"Assignee cannot be changed in {status.value}", details={"field": "assignee_id"}
        )


def ensure_deletable(status: TaskStatus) -> None:
    if status in (TaskStatus.IN_PROGRESS, TaskStatus.REVIEW):
        raise BusinessRuleViolationError(
            f"A task in {status.value} cannot be deleted", details={"status": status.value}
        )


def ensure_assignee_under_limit(active_count: int) -> None:
    """active_count — уже наявні активні задачі; нова не повинна перевищити ліміт."""
    if active_count >= MAX_ACTIVE_TASKS:
        raise BusinessRuleViolationError(
            f"Assignee already has {MAX_ACTIVE_TASKS} active tasks",
            details={"field": "assignee_id", "limit": MAX_ACTIVE_TASKS},
        )
