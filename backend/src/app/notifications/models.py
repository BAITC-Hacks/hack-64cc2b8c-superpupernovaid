from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base
from app.meetings.models import now


class Reminder(Base):
    __tablename__ = "task_reminders"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("meeting_tasks.id"), index=True)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("meeting_participants.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReminderView(BaseModel):
    id: UUID
    task_id: UUID
    meeting_id: UUID
    assignee_id: UUID | None
    task: str
    due_at: datetime
    kind: Literal["due_soon", "overdue"]
    status: Literal["pending", "read", "cancelled"]
    created_at: datetime
    read_at: datetime | None


class ReminderPage(BaseModel):
    items: list[ReminderView]
