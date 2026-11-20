from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Pagination, PathId, SessionDep
from app.schemas.comment import CommentCreate, CommentRead
from app.schemas.common import Page
from app.services.comment import CommentService

router = APIRouter(prefix="/tasks/{task_id}/comments", tags=["comments"])


@router.post("", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    task_id: PathId, data: CommentCreate, user: CurrentUser, session: SessionDep
) -> CommentRead:
    comment = await CommentService(session).create(user, task_id, data)
    return CommentRead.model_validate(comment)


@router.get("", response_model=Page[CommentRead])
async def list_comments(
    task_id: PathId, user: CurrentUser, session: SessionDep, pagination: Pagination
) -> Page[CommentRead]:
    return await CommentService(session).list_for_task(task_id, pagination)
