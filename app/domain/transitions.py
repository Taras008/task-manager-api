from app.domain.enums import TaskStatus

# Вичерпний список дозволених переходів; усе, чого тут немає, заборонено.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.BACKLOG: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.REVIEW, TaskStatus.CANCELLED}),
    TaskStatus.REVIEW: frozenset({TaskStatus.DONE}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})
ACTIVE_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.REVIEW}
)


def is_transition_allowed(current: TaskStatus, target: TaskStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
