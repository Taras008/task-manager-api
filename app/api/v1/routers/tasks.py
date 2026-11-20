from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.task import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Увага: майбутні статичні маршрути (/overdue, /stats) оголошувати ДО /{task_id}.


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, user: CurrentUser, session: SessionDep) -> TaskRead:
    task = await TaskService(session).create(user, data)
    return TaskRead.model_validate(task)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: int, user: CurrentUser, session: SessionDep) -> TaskRead:
    task = await TaskService(session).get(task_id)
    return TaskRead.model_validate(task)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int, data: TaskUpdate, user: CurrentUser, session: SessionDep
) -> TaskRead:
    task = await TaskService(session).update(user, task_id, data)
    return TaskRead.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, user: CurrentUser, session: SessionDep) -> Response:
    await TaskService(session).delete(user, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
