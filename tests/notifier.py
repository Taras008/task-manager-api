from typing import Any

from app.domain.enums import TaskStatus


class RecordingNotifier:
    """Тестовий Notifier: запам'ятовує виклики. `fail_for` — task_id, для яких кидає виняток."""

    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._fail_for = fail_for or set()

    async def notify_task_assigned(self, task_id: int, assignee_id: int) -> None:
        self.calls.append(("assigned", task_id, assignee_id))

    async def notify_status_changed(
        self, task_id: int, assignee_id: int, old: TaskStatus, new: TaskStatus
    ) -> None:
        self.calls.append(("status", task_id, assignee_id, old, new))

    async def notify_task_auto_cancelled(self, task_id: int, assignee_id: int) -> None:
        if task_id in self._fail_for:
            raise RuntimeError("notifier down")
        self.calls.append(("auto_cancelled", task_id, assignee_id))
