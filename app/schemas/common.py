from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


# Межі BIGINT: id поза діапазоном інакше дав би 500 від asyncpg замість 404/422.
MAX_BIGINT = 2**63 - 1
BigId = Annotated[int, Field(ge=1, le=MAX_BIGINT)]

# Верхня межа, щоб OFFSET не виходив за BIGINT (інакше 500 від asyncpg).
MAX_PAGE = 1_000_000


@dataclass(frozen=True, slots=True)
class PaginationParams:
    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
