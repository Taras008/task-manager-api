from dataclasses import dataclass

from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


# Верхня межа, щоб OFFSET не виходив за BIGINT (інакше 500 від asyncpg).
MAX_PAGE = 1_000_000


@dataclass(frozen=True, slots=True)
class PaginationParams:
    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
