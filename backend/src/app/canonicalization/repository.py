from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.canonicalization.errors import CanonicalizationPersistenceError
from app.canonicalization.models import CanonicalTranscript
from app.infrastructure.database import Base, get_engine


class CanonicalTranscriptRecord(Base):
    __tablename__ = "canonical_transcripts"
    __table_args__ = (
        UniqueConstraint(
            "source_audio_id", "source_hash", "profile_hash", name="uq_canonical_source_profile"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_audio_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_audio.id", ondelete="CASCADE")
    )
    source_hash: Mapped[str] = mapped_column(String(64))
    profile_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CanonicalizationRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def find(self, audio_id, source_hash, profile_hash) -> CanonicalTranscript | None:
        try:
            with self.sessions() as session:
                row = session.scalar(
                    select(CanonicalTranscriptRecord).where(
                        CanonicalTranscriptRecord.source_audio_id == audio_id,
                        CanonicalTranscriptRecord.source_hash == source_hash,
                        CanonicalTranscriptRecord.profile_hash == profile_hash,
                    )
                )
                return CanonicalTranscript.model_validate(row.payload) if row else None
        except (SQLAlchemyError, ValidationError) as exc:
            raise CanonicalizationPersistenceError from exc

    def add_or_get(self, result, source_hash, profile_hash) -> CanonicalTranscript:
        try:
            with self.sessions.begin() as session:
                session.add(
                    CanonicalTranscriptRecord(
                        source_audio_id=result.source_audio_id,
                        source_hash=source_hash,
                        profile_hash=profile_hash,
                        payload=result.model_dump(mode="json"),
                    )
                )
            return result
        except IntegrityError as exc:
            existing = self.find(result.source_audio_id, source_hash, profile_hash)
            if existing is not None:
                return existing
            raise CanonicalizationPersistenceError from exc
        except SQLAlchemyError as exc:
            raise CanonicalizationPersistenceError from exc
