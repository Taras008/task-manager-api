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

from app.domain.enums import TaskPriority, TaskStatus


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
    assignee_id: int | None = None
    deadline: AwareDatetime


class TaskUpdate(BaseModel):
    """Часткове оновлення. Поля status немає (лише PATCH /tasks/{id}/status)."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: str | None = None
    priority: ApiPriority | None = None
    assignee_id: int | None = None
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
