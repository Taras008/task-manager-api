from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comment import Comment


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, comment: Comment) -> Comment:
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def get(self, comment_id: int) -> Comment | None:
        result = await self._session.execute(
            select(Comment)
            .where(Comment.id == comment_id)
            .options(selectinload(Comment.author))
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_page(self, task_id: int, offset: int, limit: int) -> tuple[list[Comment], int]:
        """Сторінка коментарів задачі (2 запити + selectinload автора)."""
        total = (
            await self._session.execute(
                select(func.count(Comment.id)).where(Comment.task_id == task_id)
            )
        ).scalar_one()
        stmt = (
            select(Comment)
            .where(Comment.task_id == task_id)
            .order_by(asc(Comment.created_at), asc(Comment.id))
            .offset(offset)
            .limit(limit)
            .options(selectinload(Comment.author))
            .execution_options(populate_existing=True)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows), total
