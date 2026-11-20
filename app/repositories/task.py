from typing import Any

from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.enums import SortOrder, TaskSortBy
from app.domain.transitions import ACTIVE_STATUSES
from app.models.task import Task
from app.schemas.task import TaskListFilters

_LIKE_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Екранує спецсимволи LIKE, щоб `%` і `_` шукались буквально."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    async def exists(self, task_id: int, *, lock_shared: bool = False) -> bool:
        """Чи існує задача. `lock_shared` (FOR SHARE) не дає видалити її до кінця транзакції."""
        stmt = select(Task.id).where(Task.id == task_id)
        if lock_shared:
            stmt = stmt.with_for_update(read=True, of=Task)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

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

    @staticmethod
    def _apply_filters(stmt: Select[Any], filters: TaskListFilters) -> Select[Any]:
        if filters.search:
            pattern = f"%{escape_like(filters.search)}%"
            stmt = stmt.where(
                or_(
                    Task.title.ilike(pattern, escape=_LIKE_ESCAPE),
                    Task.description.ilike(pattern, escape=_LIKE_ESCAPE),
                )
            )
        if filters.status is not None:
            stmt = stmt.where(Task.status == filters.status)
        if filters.priority is not None:
            stmt = stmt.where(Task.priority == filters.priority)
        if filters.assignee_id is not None:
            stmt = stmt.where(Task.assignee_id == filters.assignee_id)
        if filters.deadline_from is not None:
            stmt = stmt.where(Task.deadline >= filters.deadline_from)
        if filters.deadline_to is not None:
            stmt = stmt.where(Task.deadline <= filters.deadline_to)
        return stmt

    @staticmethod
    def _order_by(filters: TaskListFilters) -> list[Any]:
        if filters.sort_by is None:
            # Дефолт: пріоритет ↓, дедлайн ↑, id ↑.
            return [desc(Task.priority), asc(Task.deadline), asc(Task.id)]
        column = {
            TaskSortBy.CREATED_AT: Task.created_at,
            TaskSortBy.DEADLINE: Task.deadline,
            TaskSortBy.PRIORITY: Task.priority,
        }[filters.sort_by]
        direction = desc if filters.order is SortOrder.DESC else asc
        return [direction(column), asc(Task.id)]

    async def list_page(
        self, filters: TaskListFilters, offset: int, limit: int
    ) -> tuple[list[Task], int]:
        """Сторінка задач + загальна кількість (2 запити + 2 selectinload)."""
        total = (
            await self._session.execute(self._apply_filters(select(func.count(Task.id)), filters))
        ).scalar_one()
        stmt = (
            self._apply_filters(select(Task), filters)
            .order_by(*self._order_by(filters))
            .offset(offset)
            .limit(limit)
            .options(selectinload(Task.author), selectinload(Task.assignee))
            .execution_options(populate_existing=True)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows), total
