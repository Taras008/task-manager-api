from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def add(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.flush()
        return task

    async def delete(self, task: Task) -> None:
        await self._session.delete(task)
        await self._session.flush()
