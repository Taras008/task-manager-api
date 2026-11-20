from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_for_update(self, user_id: int) -> User | None:
        """Блокує рядок користувача — серіалізує перевірку ліміту активних задач.

        `key_share=True` дає FOR NO KEY UPDATE: два такі локи конфліктують між собою (ліміт
        серіалізується), але не з FOR KEY SHARE, який INSERT задачі бере на рядки автора й
        виконавця для FK-перевірки. Звичайний FOR UPDATE давав deadlock при зустрічних
        створеннях (A→B і B→A).
        """
        result = await self._session.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user
