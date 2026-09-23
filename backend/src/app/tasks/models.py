from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base
from app.meetings.models import now


class Task(Base):
    __tablename__ = "meeting_tasks"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    transcript_id: Mapped[UUID | None] = mapped_column(ForeignKey("speech_transcripts.id"))
    text: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("meeting_participants.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    source_segment_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
