from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


def now():
    return datetime.now(UTC)


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    processing_status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    title: Mapped[str] = mapped_column(String(255))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language_hint: Mapped[str] = mapped_column(String(10), default="ru")
    expected_participant_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RecordingConsent(Base):
    __tablename__ = "meeting_recording_consents"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Participant(Base):
    __tablename__ = "meeting_participants"
    __table_args__ = (
        UniqueConstraint("transcript_id", "speaker_id", name="uq_participant_speaker"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    transcript_id: Mapped[UUID] = mapped_column(ForeignKey("speech_transcripts.id"))
    speaker_id: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str | None] = mapped_column(String(255))


class ProcessingStep(Base):
    __tablename__ = "meeting_processing_steps"
    media_id: Mapped[UUID] = mapped_column(ForeignKey("media_assets.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(30), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChangeAudit(Base):
    __tablename__ = "meeting_change_audit"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(50))
    changes: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
