from fastapi import BackgroundTasks

from app.domain.events import AssigneeAssigned, StatusChanged, TaskEvent
from app.services.notifier import Notifier


def dispatch_events(
    background_tasks: BackgroundTasks, notifier: Notifier, events: list[TaskEvent]
) -> None:
    """Планує нотифікації на після відправлення відповіді (HTTP-шар, не сервіс)."""
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
