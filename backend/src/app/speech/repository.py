from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.infrastructure.database import Base, get_engine
from app.speech.errors import SpeechPersistenceError
from app.speech.models import AttributedTranscript


class TranscriptRecord(Base):
    __tablename__ = "speech_transcripts"
    __table_args__ = (
        UniqueConstraint("source_audio_id", "profile_hash", name="uq_speech_profile"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_audio_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_audio.id", ondelete="CASCADE")
    )
    profile_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SpeechRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def find(self, audio_id: UUID, profile_hash: str) -> AttributedTranscript | None:
        try:
            with self.sessions() as session:
                row = session.scalar(
                    select(TranscriptRecord).where(
                        TranscriptRecord.source_audio_id == audio_id,
                        TranscriptRecord.profile_hash == profile_hash,
                    )
                )
                return AttributedTranscript.model_validate(row.payload) if row else None
        except (SQLAlchemyError, ValidationError) as exc:
            raise SpeechPersistenceError from exc

    def add_or_get(self, result: AttributedTranscript, profile_hash: str) -> AttributedTranscript:
        try:
            with self.sessions.begin() as session:
                record = TranscriptRecord(
                    source_audio_id=result.source_audio_id,
                    profile_hash=profile_hash,
                    payload=result.model_dump(mode="json"),
                )
                session.add(record)
                session.flush()
                from app.audio.models import NormalizedAudio
                from app.media.models import MediaAsset
                from app.meetings.models import Meeting
                from app.meetings.repository import ensure_participants

                audio = session.get(NormalizedAudio, result.source_audio_id)
                media = session.get(MediaAsset, audio.source_media_id) if audio else None
                if media and session.get(Meeting, media.meeting_id):
                    ensure_participants(session, record, media.meeting_id)
            return result
        except IntegrityError as exc:
            existing = self.find(result.source_audio_id, profile_hash)
            if existing is not None:
                return existing
            raise SpeechPersistenceError from exc
        except SQLAlchemyError as exc:
            raise SpeechPersistenceError from exc
