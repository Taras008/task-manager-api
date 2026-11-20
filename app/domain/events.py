from dataclasses import dataclass

from app.domain.enums import TaskStatus


@dataclass(frozen=True, slots=True)
class AssigneeAssigned:
    """Виконавця призначено (або змінено) на задачу."""

    task_id: int
    assignee_id: int


@dataclass(frozen=True, slots=True)
class StatusChanged:
    """Статус задачі змінено вручну; нотифікація йде виконавцю."""

    task_id: int
    assignee_id: int
    old: TaskStatus
    new: TaskStatus


TaskEvent = AssigneeAssigned | StatusChanged


@dataclass(frozen=True, slots=True)
class TaskAutoCancelled:
    """Задачу автоматично скасовано воркером (прострочений дедлайн)."""

    task_id: int
    assignee_id: int | None
