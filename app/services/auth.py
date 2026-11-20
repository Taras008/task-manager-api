import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.domain.exceptions import AuthenticationError, EmailAlreadyRegisteredError
from app.models.user import User
from app.repositories.user import UserRepository


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def register(self, email: str, password: str) -> User:
        email = email.strip().lower()
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError("Email is already registered")
        # Argon2 CPU-важкий: виносимо з event loop.
        hashed = await asyncio.to_thread(hash_password, password)
        user = User(email=email, hashed_password=hashed, created_at=clock.now())
        try:
            await self._users.add(user)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise EmailAlreadyRegisteredError("Email is already registered") from exc
        return user

    async def authenticate(self, email: str, password: str) -> str:
        user = await self._users.get_by_email(email.strip().lower())
        if user is None:
            await asyncio.to_thread(verify_dummy_password, password)
            raise AuthenticationError("Incorrect email or password")
        if not await asyncio.to_thread(verify_password, password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password")
        return create_access_token(str(user.id))

    async def get_user_from_token(self, token: str) -> User:
        subject = decode_access_token(token)
        try:
            user_id = int(subject)
        except ValueError as exc:
            raise AuthenticationError("Invalid authentication token") from exc
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("Invalid authentication token")
        return user
