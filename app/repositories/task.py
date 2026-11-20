from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.transitions import ACTIVE_STATUSES
from app.models.task import Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, task_id: int) -> Task | None:
        """Задача з автором і виконавцем (без N+1)."""
        result = await self._session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(selectinload(Task.author), selectinload(Task.assignee))
            # Гарантує свіжі дані після commit у тій самій сесії.
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, task_id: int) -> Task | None:
        """Те саме, що get, але з блокуванням рядка задачі (FOR UPDATE)."""
        result = await self._session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(selectinload(Task.author), selectinload(Task.assignee))
            .with_for_update(of=Task)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def count_active_for_assignee(self, assignee_id: int) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.assignee_id == assignee_id, Task.status.in_(ACTIVE_STATUSES))
        )
        return result.scalar_one()

    async def add(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.flush()
        return task

    async def delete(self, task: Task) -> None:
        await self._session.delete(task)
        await self._session.flush()
