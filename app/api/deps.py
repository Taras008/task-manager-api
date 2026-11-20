from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Одна сесія на запит. Commit робить сервіс, тут лише закриття."""
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session
