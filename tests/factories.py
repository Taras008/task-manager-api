from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.security import create_access_token, hash_password
from app.models.user import User

DEFAULT_PASSWORD = "correct-horse-battery"


async def create_user(
    session_factory: async_sessionmaker[AsyncSession],
    email: str = "user@example.com",
    password: str = DEFAULT_PASSWORD,
) -> User:
    async with session_factory() as session:
        user = User(email=email, hashed_password=hash_password(password), created_at=clock.now())
        session.add(user)
        await session.commit()
        return user


def auth_headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}
