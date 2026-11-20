from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-secret-change-me-in-production"
# Плейсхолдери, що потрапляють у репозиторій (config, .env.example, compose) — у prod заборонені.
INSECURE_JWT_SECRETS = frozenset({DEFAULT_JWT_SECRET, "change-me-to-a-long-random-string"})
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    test_database_url: str = "postgresql+asyncpg://app:app@localhost:5433/app_test"

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    overdue_interval_seconds: int = 60

    @model_validator(mode="after")
    def _check_prod_secret(self) -> Self:
        if self.environment == "prod" and (
            self.jwt_secret in INSECURE_JWT_SECRETS or len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH
        ):
            raise ValueError(
                f"JWT_SECRET must be set to a unique value of at least "
                f"{MIN_JWT_SECRET_LENGTH} characters when ENVIRONMENT=prod"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
