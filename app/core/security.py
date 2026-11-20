from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core import clock
from app.core.config import get_settings
from app.domain.exceptions import AuthenticationError

_password_hash = PasswordHash((Argon2Hasher(),))
# Фіктивний хеш: перевіряємо його, коли користувача немає,
# щоб час відповіді не видавав існування email.
_DUMMY_HASH = _password_hash.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Невалідний/невідомий формат хешу трактуємо як невдалу перевірку (401), а не 500."""
    try:
        return _password_hash.verify(password, hashed)
    except PwdlibError:
        return False


def verify_dummy_password(password: str) -> None:
    _password_hash.verify(password, _DUMMY_HASH)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    issued_at = clock.now()
    expires = issued_at + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": subject, "iat": issued_at, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Повертає `sub`. Строк дії перевіряємо через clock.now(), а не системний час PyJWT."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False, "verify_iat": False, "require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid authentication token") from exc
    subject = payload["sub"]
    exp = payload["exp"]
    # bool — підклас int, але не є валідним exp.
    if not isinstance(subject, str) or isinstance(exp, bool) or not isinstance(exp, int | float):
        raise AuthenticationError("Invalid authentication token")
    try:
        expires = datetime.fromtimestamp(exp, tz=UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise AuthenticationError("Invalid authentication token") from exc
    if expires <= clock.now():
        raise AuthenticationError("Invalid authentication token")
    return subject
