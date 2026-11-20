from enum import IntEnum, StrEnum


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
