from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import TaskStatus as S
from app.domain.exceptions import (
    BusinessRuleViolationError,
    DomainValidationError,
    InvalidStatusTransitionError,
)
from app.domain.rules import (
    MAX_ACTIVE_TASKS,
    ensure_assignee_change_allowed,
    ensure_assignee_under_limit,
    ensure_can_enter_status,
    ensure_deletable,
    ensure_task_editable,
    ensure_transition_allowed,
    validate_deadline_not_in_past,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_past_deadline_rejected() -> None:
    with pytest.raises(DomainValidationError):
        validate_deadline_not_in_past(NOW - timedelta(seconds=1), NOW)


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(days=1)])
def test_now_and_future_deadline_allowed(delta: timedelta) -> None:
    validate_deadline_not_in_past(NOW + delta, NOW)


# --- Етап 3: правила статусів ---

FUTURE = NOW + timedelta(days=1)


def test_invalid_transition_rejected() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        ensure_transition_allowed(S.REVIEW, S.IN_PROGRESS)


def test_valid_transition_allowed() -> None:
    ensure_transition_allowed(S.BACKLOG, S.IN_PROGRESS)


@pytest.mark.parametrize("target", [S.IN_PROGRESS, S.REVIEW, S.DONE])
def test_assignee_required(target: S) -> None:
    with pytest.raises(BusinessRuleViolationError):
        ensure_can_enter_status(target, None, FUTURE, NOW)


def test_assignee_not_required_for_cancelled() -> None:
    ensure_can_enter_status(S.CANCELLED, None, FUTURE, NOW)


def test_done_with_expired_deadline_rejected() -> None:
    with pytest.raises(BusinessRuleViolationError):
        ensure_can_enter_status(S.DONE, 1, NOW - timedelta(seconds=1), NOW)


def test_done_with_deadline_equal_now_allowed() -> None:
    ensure_can_enter_status(S.DONE, 1, NOW, NOW)


def test_expired_deadline_does_not_block_in_progress() -> None:
    ensure_can_enter_status(S.IN_PROGRESS, 1, NOW - timedelta(days=1), NOW)


@pytest.mark.parametrize("status", [S.DONE, S.CANCELLED])
def test_terminal_tasks_read_only(status: S) -> None:
    with pytest.raises(BusinessRuleViolationError):
        ensure_task_editable(status)


@pytest.mark.parametrize("status", [S.BACKLOG, S.IN_PROGRESS, S.REVIEW])
def test_active_tasks_editable(status: S) -> None:
    ensure_task_editable(status)


@pytest.mark.parametrize("status", [S.REVIEW, S.DONE])
def test_assignee_change_forbidden(status: S) -> None:
    with pytest.raises(BusinessRuleViolationError):
        ensure_assignee_change_allowed(status)


@pytest.mark.parametrize("status", [S.BACKLOG, S.IN_PROGRESS])
def test_assignee_change_allowed(status: S) -> None:
    ensure_assignee_change_allowed(status)


@pytest.mark.parametrize("status", [S.IN_PROGRESS, S.REVIEW])
def test_delete_forbidden(status: S) -> None:
    with pytest.raises(BusinessRuleViolationError):
        ensure_deletable(status)


@pytest.mark.parametrize("status", [S.BACKLOG, S.DONE, S.CANCELLED])
def test_delete_allowed(status: S) -> None:
    ensure_deletable(status)


def test_limit_tenth_allowed_eleventh_rejected() -> None:
    assert MAX_ACTIVE_TASKS == 10
    ensure_assignee_under_limit(9)  # 10-та
    with pytest.raises(BusinessRuleViolationError):
        ensure_assignee_under_limit(10)  # 11-та
