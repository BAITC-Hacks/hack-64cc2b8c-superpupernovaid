from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.meetings.schemas import Input

TaskStatus = Literal["in_progress", "overdue", "completed"]


class TaskPatch(Input):
    text: str | None = Field(default=None, min_length=1, max_length=10000)
    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    due_at: AwareDatetime | None = None
    priority: Literal["low", "normal", "high"] | None = None

    @model_validator(mode="after")
    def nonnull(self):
        for key in ("text", "status", "priority"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class TaskCreate(Input):
    text: str = Field(min_length=1, max_length=10000)
    assignee_id: UUID | None = None
    due_at: AwareDatetime | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    source_segment_ids: list[UUID] = Field(default_factory=list, max_length=100)


class AssigneeView(BaseModel):
    id: UUID
    display_name: str | None


class TaskView(BaseModel):
    id: UUID
    meeting_id: UUID
    text: str
    assignee: AssigneeView | None
    due_at: datetime | None
    status: TaskStatus
    priority: str
    source_segment_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskView]
    next_cursor: str | None
