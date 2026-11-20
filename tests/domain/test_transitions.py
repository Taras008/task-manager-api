from itertools import product

import pytest

from app.domain.enums import TaskStatus as S
from app.domain.transitions import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    is_transition_allowed,
)

ALLOWED = {
    (S.BACKLOG, S.IN_PROGRESS),
    (S.BACKLOG, S.CANCELLED),
    (S.IN_PROGRESS, S.REVIEW),
    (S.IN_PROGRESS, S.CANCELLED),
    (S.REVIEW, S.DONE),
}


@pytest.mark.parametrize(("current", "target"), list(product(S, S)))
def test_transition_matrix(current: S, target: S) -> None:
    assert is_transition_allowed(current, target) is ((current, target) in ALLOWED)


def test_every_status_has_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_terminal_and_active_sets() -> None:
    assert {S.DONE, S.CANCELLED} == set(TERMINAL_STATUSES)
    assert {S.BACKLOG, S.IN_PROGRESS, S.REVIEW} == set(ACTIVE_STATUSES)
