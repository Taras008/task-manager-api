from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    test_database_url: str = "postgresql+asyncpg://app:app@localhost:5433/app_test"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    overdue_interval_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
