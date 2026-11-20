from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

from app.schemas.task import UserBrief

CommentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: CommentText


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    text: str
    created_at: AwareDatetime
    author: UserBrief
