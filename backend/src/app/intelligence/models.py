from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base
from app.meetings.models import now


class MeetingAnalysis(Base):
    __tablename__ = "meeting_analyses"
    transcript_id: Mapped[UUID] = mapped_column(
        ForeignKey("speech_transcripts.id"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Decision(Base):
    __tablename__ = "meeting_decisions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(
        ForeignKey("meeting_analyses.transcript_id"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    source_segment_ids: Mapped[list] = mapped_column(JSON)
