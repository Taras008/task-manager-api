from datetime import datetime, timedelta

import jwt
import pytest

from app.core import clock
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.domain.exceptions import AuthenticationError


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret-pass")

    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("other", hashed)


def test_token_roundtrip() -> None:
    assert decode_access_token(create_access_token("42")) == "42"


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = create_access_token("42", expires_delta=timedelta(minutes=5))
    real_now = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real_now + timedelta(minutes=6))

    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_token_valid_before_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    token = create_access_token("42", expires_delta=timedelta(minutes=5))
    real_now = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real_now + timedelta(minutes=4))

    assert decode_access_token(token) == "42"


def test_forged_signature_is_rejected() -> None:
    settings = get_settings()
    forged = jwt.encode(
        {"sub": "1", "exp": clock.now() + timedelta(hours=1)},
        "wrong-key-wrong-key-wrong-key-12345",
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


@pytest.mark.parametrize("claims", [{"sub": "1"}, {"exp": 4_102_444_800}])
def test_token_without_required_claims_is_rejected(claims: dict[str, int | str | datetime]) -> None:
    settings = get_settings()
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    with pytest.raises(AuthenticationError):
        decode_access_token(token)


@pytest.mark.parametrize("exp", ["tomorrow", 1e20, -1e20, True, None])
def test_token_with_invalid_exp_is_rejected(exp: object) -> None:
    settings = get_settings()
    token = jwt.encode(
        {"sub": "1", "exp": exp}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token)


@pytest.mark.parametrize("broken", ["", "garbage", "$argon2id$broken", "$2b$12$notargon"])
def test_verify_password_with_broken_hash_returns_false(broken: str) -> None:
    assert verify_password("whatever", broken) is False
