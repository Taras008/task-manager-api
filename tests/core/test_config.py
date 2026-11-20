import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings

STRONG_SECRET = "x" * 40


def test_prod_rejects_default_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(environment="prod")


def test_prod_rejects_explicit_default_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod", jwt_secret=DEFAULT_JWT_SECRET)


def test_prod_rejects_env_example_placeholder() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod", jwt_secret="change-me-to-a-long-random-string")


def test_prod_rejects_short_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod", jwt_secret="short-but-unique")


def test_prod_accepts_strong_secret() -> None:
    assert Settings(environment="prod", jwt_secret=STRONG_SECRET).environment == "prod"


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_non_prod_allows_default_secret(environment: str) -> None:
    assert Settings(environment=environment).jwt_secret == DEFAULT_JWT_SECRET


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")
