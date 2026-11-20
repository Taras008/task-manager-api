from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, Pagination, SessionDep
from app.schemas.common import Page
from app.schemas.task import (
    TaskCreate,
    TaskListFilters,
    TaskRead,
    TaskStats,
    TaskStatusUpdate,
    TaskUpdate,
)
from app.services.task import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Увага: статичні маршрути (/overdue, /stats) оголошені ДО /{task_id}.


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, user: CurrentUser, session: SessionDep) -> TaskRead:
    task = await TaskService(session).create(user, data)
    return TaskRead.model_validate(task)


@router.get("", response_model=Page[TaskRead])
async def list_tasks(
    user: CurrentUser,
    session: SessionDep,
    filters: Annotated[TaskListFilters, Query()],
    pagination: Pagination,
) -> Page[TaskRead]:
    return await TaskService(session).list(filters, pagination.page, pagination.size)


@router.get("/overdue", response_model=Page[TaskRead])
async def list_overdue_tasks(
    user: CurrentUser, session: SessionDep, pagination: Pagination
) -> Page[TaskRead]:
    return await TaskService(session).list_overdue(pagination.page, pagination.size)


@router.get("/stats", response_model=TaskStats)
async def task_stats(user: CurrentUser, session: SessionDep) -> TaskStats:
    return await TaskService(session).stats()


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


@router.patch("/{task_id}/status", response_model=TaskRead)
async def change_task_status(
    task_id: int, data: TaskStatusUpdate, user: CurrentUser, session: SessionDep
) -> TaskRead:
    task = await TaskService(session).change_status(user, task_id, data.status)
    return TaskRead.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, user: CurrentUser, session: SessionDep) -> Response:
    await TaskService(session).delete(user, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
