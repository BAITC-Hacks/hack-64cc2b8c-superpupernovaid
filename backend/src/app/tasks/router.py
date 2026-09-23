from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from app.tasks.repository import TaskRepository, get_tasks
from app.tasks.schemas import TaskCreate, TaskPage, TaskPatch, TaskStatus, TaskView

router = APIRouter(prefix="/api/v1", tags=["Tasks"])
Repo = Annotated[TaskRepository, Depends(get_tasks)]


@router.get("/tasks", response_model=TaskPage)
def list_tasks(
    repository: Repo,
    status: TaskStatus | None = None,
    assignee_id: UUID | None = None,
    due_before: AwareDatetime | None = None,
    q: str | None = Query(None, max_length=200),
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(50, ge=1, le=100),
):
    return repository.list(
        status=status,
        assignee_id=assignee_id,
        due_before=due_before,
        q=q,
        cursor=cursor,
        limit=limit,
    )


@router.patch("/tasks/{task_id}", response_model=TaskView)
def patch_task(task_id: UUID, payload: TaskPatch, repository: Repo):
    return repository.patch(task_id, payload)


@router.get("/meetings/{meeting_id}/tasks", response_model=TaskPage)
def meeting_tasks(
    meeting_id: UUID,
    repository: Repo,
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(50, ge=1, le=100),
):
    return repository.list(meeting_id=meeting_id, cursor=cursor, limit=limit)


@router.post("/meetings/{meeting_id}/tasks", response_model=TaskView, status_code=201)
def create_task(meeting_id: UUID, payload: TaskCreate, repository: Repo):
    return repository.create(meeting_id, payload)
