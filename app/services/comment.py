import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.domain.exceptions import NotFoundError
from app.models.comment import Comment
from app.models.user import User
from app.repositories.comment import CommentRepository
from app.repositories.task import TaskRepository
from app.schemas.comment import CommentCreate, CommentRead
from app.schemas.common import Page, PaginationParams


class CommentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._comments = CommentRepository(session)
        self._tasks = TaskRepository(session)

    async def _ensure_task_exists(self, task_id: int, *, lock_shared: bool = False) -> None:
        if not await self._tasks.exists(task_id, lock_shared=lock_shared):
            raise NotFoundError("Task not found")

    async def create(self, author: User, task_id: int, data: CommentCreate) -> Comment:
        # Коментувати можна задачі в будь-якому статусі (правило №5).
        # FOR SHARE: паралельне видалення задачі не дасть FK-помилки (500) між перевіркою і INSERT.
        await self._ensure_task_exists(task_id, lock_shared=True)
        comment = Comment(
            task_id=task_id,
            author_id=author.id,
            text=data.text,
            created_at=clock.now(),
        )
        await self._comments.add(comment)
        comment_id = comment.id
        await self._session.commit()
        loaded = await self._comments.get(comment_id)
        if loaded is None:
            raise NotFoundError("Comment not found")
        return loaded

    async def list_for_task(self, task_id: int, pagination: PaginationParams) -> Page[CommentRead]:
        await self._ensure_task_exists(task_id)
        comments, total = await self._comments.list_page(
            task_id, pagination.offset, pagination.size
        )
        return Page[CommentRead](
            items=[CommentRead.model_validate(c) for c in comments],
            total=total,
            page=pagination.page,
            size=pagination.size,
            pages=math.ceil(total / pagination.size),
        )
