import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.domain.enums import TaskPriority, TaskStatus
from app.domain.events import AssigneeAssigned, StatusChanged, TaskEvent
from app.domain.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.domain.rules import (
    ensure_assignee_change_allowed,
    ensure_assignee_under_limit,
    ensure_can_enter_status,
    ensure_deletable,
    ensure_task_editable,
    ensure_transition_allowed,
    validate_deadline_not_in_past,
)
from app.models.task import Task
from app.models.user import User
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.schemas.common import Page
from app.schemas.task import TaskCreate, TaskListFilters, TaskRead, TaskStats, TaskUpdate


class TaskService:
    """Порядок блокувань завжди: рядок задачі, потім рядок користувача (без deadlock)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tasks = TaskRepository(session)
        self._users = UserRepository(session)
        # Події для нотифікацій; наповнюються після успішного commit.
        self.events: list[TaskEvent] = []

    async def _ensure_assignee_exists(self, assignee_id: int) -> None:
        if await self._users.get_by_id(assignee_id) is None:
            raise DomainValidationError("Assignee does not exist", details={"field": "assignee_id"})

    async def _ensure_assignee_capacity(self, assignee_id: int) -> None:
        """Блокує виконавця й перевіряє ліміт активних задач (правило №7)."""
        if await self._users.get_for_update(assignee_id) is None:
            raise DomainValidationError("Assignee does not exist", details={"field": "assignee_id"})
        ensure_assignee_under_limit(await self._tasks.count_active_for_assignee(assignee_id))

    async def _load(self, task_id: int) -> Task:
        task = await self._tasks.get(task_id)
        if task is None:
            raise NotFoundError("Task not found")
        return task

    async def _load_for_update(self, task_id: int) -> Task:
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise NotFoundError("Task not found")
        return task

    async def _load_owned_for_update(self, user: User, task_id: int) -> Task:
        task = await self._load_for_update(task_id)
        if task.author_id != user.id:
            raise PermissionDeniedError("Only the author can modify this task")
        return task

    @staticmethod
    def _page(tasks: list[Task], total: int, page: int, size: int) -> Page[TaskRead]:
        return Page[TaskRead](
            items=[TaskRead.model_validate(t) for t in tasks],
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size),
        )

    async def list(self, filters: TaskListFilters, page: int, size: int) -> Page[TaskRead]:
        tasks, total = await self._tasks.list_page(filters, (page - 1) * size, size)
        return self._page(tasks, total, page, size)

    async def list_overdue(self, page: int, size: int) -> Page[TaskRead]:
        tasks, total = await self._tasks.list_overdue(clock.now(), (page - 1) * size, size)
        return self._page(tasks, total, page, size)

    async def stats(self) -> TaskStats:
        row = await self._tasks.stats_row(clock.now())
        return TaskStats(
            total=row.total,
            by_status={s: getattr(row, f"status_{s.value}") for s in TaskStatus},
            by_priority={
                p.name.lower(): getattr(row, f"priority_{p.name.lower()}") for p in TaskPriority
            },
            overdue=row.overdue,
            active=row.active,
        )

    async def create(self, author: User, data: TaskCreate) -> Task:
        now = clock.now()
        validate_deadline_not_in_past(data.deadline, now)
        if data.assignee_id is not None:
            await self._ensure_assignee_capacity(data.assignee_id)
        task = Task(
            title=data.title,
            description=data.description,
            priority=data.priority,
            author_id=author.id,
            assignee_id=data.assignee_id,
            deadline=data.deadline,
            created_at=now,
            updated_at=now,
        )
        await self._tasks.add(task)
        task_id = task.id
        await self._session.commit()
        # Не сповіщаємо про самопризначення (той самий принцип, що й у change_status).
        if data.assignee_id is not None and data.assignee_id != author.id:
            self.events.append(AssigneeAssigned(task_id, data.assignee_id))
        return await self._load(task_id)

    async def get(self, task_id: int) -> Task:
        return await self._load(task_id)

    async def update(self, user: User, task_id: int, data: TaskUpdate) -> Task:
        task = await self._load_owned_for_update(user, task_id)
        changes = {name: getattr(data, name) for name in data.model_fields_set}

        # 422 (доменна валідація) передує 409 (правила стану).
        # Дедлайн перевіряємо лише коли він справді змінюється (правило №3).
        new_deadline = changes.get("deadline")
        if new_deadline is not None and new_deadline != task.deadline:
            validate_deadline_not_in_past(new_deadline, clock.now())
        new_assignee = changes.get("assignee_id")
        assignee_changes = "assignee_id" in changes and new_assignee != task.assignee_id
        if new_assignee is not None and assignee_changes:
            await self._ensure_assignee_exists(new_assignee)

        ensure_task_editable(task.status)
        if assignee_changes:
            ensure_assignee_change_allowed(task.status)
            if new_assignee is not None:
                await self._ensure_assignee_capacity(new_assignee)

        changed = False
        for field, value in changes.items():
            if getattr(task, field) != value:
                setattr(task, field, value)
                changed = True
        if changed:
            task.updated_at = clock.now()
        await self._session.commit()
        if assignee_changes and new_assignee is not None and new_assignee != user.id:
            self.events.append(AssigneeAssigned(task_id, new_assignee))
        return await self._load(task_id)

    async def change_status(self, user: User, task_id: int, target: TaskStatus) -> Task:
        task = await self._load_for_update(task_id)
        if user.id not in (task.author_id, task.assignee_id):
            raise PermissionDeniedError("Only the author or the assignee can change the status")
        now = clock.now()
        ensure_transition_allowed(task.status, target)
        ensure_can_enter_status(target, task.assignee_id, task.deadline, now)
        old_status = task.status
        assignee_id = task.assignee_id
        task.status = target
        task.updated_at = now
        await self._session.commit()
        # Не сповіщаємо виконавця про його власну дію.
        if assignee_id is not None and assignee_id != user.id:
            self.events.append(StatusChanged(task_id, assignee_id, old_status, target))
        return await self._load(task_id)

    async def delete(self, user: User, task_id: int) -> None:
        task = await self._load_owned_for_update(user, task_id)
        ensure_deletable(task.status)
        await self._tasks.delete(task)
        await self._session.commit()
