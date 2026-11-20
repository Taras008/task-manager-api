from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field


def _normalize_email(value: str) -> str:
    return value.strip().lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]


class UserCreate(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
