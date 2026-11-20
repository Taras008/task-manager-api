from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Path, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.common import MAX_BIGINT, MAX_PAGE, PaginationParams
from app.services.auth import AuthService
from app.services.notifier import Notifier

PathId = Annotated[int, Path(ge=1, le=MAX_BIGINT)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Одна сесія на запит. Commit робить сервіс, тут лише закриття."""
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_notifier(request: Request) -> Notifier:
    notifier: Notifier = request.app.state.notifier
    return notifier


NotifierDep = Annotated[Notifier, Depends(get_notifier)]


async def get_current_user(
    session: SessionDep, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    return await AuthService(session).get_user_from_token(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_pagination(
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, size=size)


Pagination = Annotated[PaginationParams, Depends(get_pagination)]
