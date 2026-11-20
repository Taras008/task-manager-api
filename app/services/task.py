from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.domain.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.domain.rules import validate_deadline_not_in_past
from app.models.task import Task
from app.models.user import User
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tasks = TaskRepository(session)
        self._users = UserRepository(session)

    async def _ensure_assignee_exists(self, assignee_id: int) -> None:
        if await self._users.get_by_id(assignee_id) is None:
            raise DomainValidationError("Assignee does not exist", details={"field": "assignee_id"})

    async def _load(self, task_id: int) -> Task:
        task = await self._tasks.get(task_id)
        if task is None:
            raise NotFoundError("Task not found")
        return task

    async def _load_owned(self, user: User, task_id: int) -> Task:
        task = await self._load(task_id)
        if task.author_id != user.id:
            raise PermissionDeniedError("Only the author can modify this task")
        return task

    async def create(self, author: User, data: TaskCreate) -> Task:
        now = clock.now()
        validate_deadline_not_in_past(data.deadline, now)
        if data.assignee_id is not None:
            await self._ensure_assignee_exists(data.assignee_id)
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
        return await self._load(task_id)

    async def get(self, task_id: int) -> Task:
        return await self._load(task_id)

    async def update(self, user: User, task_id: int, data: TaskUpdate) -> Task:
        task = await self._load_owned(user, task_id)
        changes = {name: getattr(data, name) for name in data.model_fields_set}

        # Дедлайн перевіряємо лише коли він справді змінюється (правило №3).
        new_deadline = changes.get("deadline")
        if new_deadline is not None and new_deadline != task.deadline:
            validate_deadline_not_in_past(new_deadline, clock.now())
        new_assignee = changes.get("assignee_id")
        if new_assignee is not None and new_assignee != task.assignee_id:
            await self._ensure_assignee_exists(new_assignee)

        changed = False
        for field, value in changes.items():
            if getattr(task, field) != value:
                setattr(task, field, value)
                changed = True
        if changed:
            task.updated_at = clock.now()
        await self._session.commit()
        return await self._load(task_id)

    async def delete(self, user: User, task_id: int) -> None:
        task = await self._load_owned(user, task_id)
        await self._tasks.delete(task)
        await self._session.commit()
