from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from app.domain.enums import SortOrder, TaskPriority, TaskSortBy, TaskStatus
from app.schemas.common import BigId


def _priority_from_name(value: object) -> object:
    if isinstance(value, TaskPriority):
        return value
    if isinstance(value, str):
        try:
            return TaskPriority[value.strip().upper()]
        except KeyError:
            raise ValueError("priority must be one of: low, medium, high") from None
    raise ValueError("priority must be one of: low, medium, high")


# В API пріоритет — low/medium/high; SMALLINT лишається лише в БД.
ApiPriority = Annotated[
    TaskPriority,
    BeforeValidator(_priority_from_name),
    PlainSerializer(lambda p: p.name.lower(), return_type=str),
]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: str | None = None
    priority: ApiPriority = TaskPriority.MEDIUM
    assignee_id: BigId | None = None
    deadline: AwareDatetime


class TaskUpdate(BaseModel):
    """Часткове оновлення. Поля status немає (лише PATCH /tasks/{id}/status)."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: str | None = None
    priority: ApiPriority | None = None
    assignee_id: BigId | None = None
    deadline: AwareDatetime | None = None

    @model_validator(mode="after")
    def _forbid_null_required_fields(self) -> Self:
        for name in ("title", "priority", "deadline"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus


class TaskListFilters(BaseModel):
    """Query-параметри списку задач (межі дедлайну включні).

    extra="forbid" тут не можна: у ту саму query-модель потрапляють page/size.
    """

    search: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)] = None
    status: TaskStatus | None = None
    priority: ApiPriority | None = None
    assignee_id: BigId | None = None
    deadline_from: AwareDatetime | None = None
    deadline_to: AwareDatetime | None = None
    sort_by: TaskSortBy | None = None
    order: SortOrder = SortOrder.ASC

    @model_validator(mode="after")
    def _check_deadline_range(self) -> Self:
        if self.search == "":
            self.search = None
        if (
            self.deadline_from is not None
            and self.deadline_to is not None
            and self.deadline_from > self.deadline_to
        ):
            raise ValueError("deadline_from must not be later than deadline_to")
        return self


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: ApiPriority
    deadline: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime
    author: UserBrief
    assignee: UserBrief | None


class TaskStats(BaseModel):
    """Глобальна статистика задач; by_status/by_priority містять усі ключі (навіть з 0)."""

    total: int
    by_status: dict[TaskStatus, int]
    by_priority: dict[str, int]
    overdue: int
    active: int
