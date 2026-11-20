import logging
from typing import Protocol

from fastapi import BackgroundTasks

from app.domain.enums import TaskStatus
from app.domain.events import AssigneeAssigned, StatusChanged, TaskEvent

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """Інтерфейс нотифікацій. Приймає прості значення, а не ORM-об'єкти чи request-сесію."""

    async def notify_task_assigned(self, task_id: int, assignee_id: int) -> None: ...

    async def notify_status_changed(
        self, task_id: int, assignee_id: int, old: TaskStatus, new: TaskStatus
    ) -> None: ...

    async def notify_task_auto_cancelled(self, task_id: int, assignee_id: int) -> None: ...


class LoggingNotifier:
    """Stub-реалізація: структурований лог замість реальної доставки."""

    async def notify_task_assigned(self, task_id: int, assignee_id: int) -> None:
        logger.info(
            "Notification: task assigned",
            extra={"event": "task_assigned", "task_id": task_id, "assignee_id": assignee_id},
        )

    async def notify_status_changed(
        self, task_id: int, assignee_id: int, old: TaskStatus, new: TaskStatus
    ) -> None:
        logger.info(
            "Notification: task status changed",
            extra={
                "event": "task_status_changed",
                "task_id": task_id,
                "assignee_id": assignee_id,
                "old_status": old.value,
                "new_status": new.value,
            },
        )

    async def notify_task_auto_cancelled(self, task_id: int, assignee_id: int) -> None:
        logger.info(
            "Notification: task auto-cancelled (overdue)",
            extra={
                "event": "task_auto_cancelled",
                "task_id": task_id,
                "assignee_id": assignee_id,
            },
        )


def dispatch_events(
    background_tasks: BackgroundTasks, notifier: Notifier, events: list[TaskEvent]
) -> None:
    """Планує нотифікації на після відправлення відповіді."""
    for event in events:
        match event:
            case AssigneeAssigned():
                background_tasks.add_task(
                    notifier.notify_task_assigned, event.task_id, event.assignee_id
                )
            case StatusChanged():
                background_tasks.add_task(
                    notifier.notify_status_changed,
                    event.task_id,
                    event.assignee_id,
                    event.old,
                    event.new,
                )
