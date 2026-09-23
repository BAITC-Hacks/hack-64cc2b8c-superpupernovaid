from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.infrastructure.database import Base, get_engine
from app.intelligence.pipeline.errors import AnalysisPersistenceError
from app.intelligence.pipeline.models import MeetingAnalysis


class MeetingAnalysisRecord(Base):
    __tablename__ = "agent_analysis_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "source_audio_id",
            "source_hash",
            "profile_hash",
            name="uq_meeting_analysis_source_profile",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    source_audio_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_audio.id", ondelete="CASCADE")
    )
    source_hash: Mapped[str] = mapped_column(String(64))
    profile_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class MeetingAnalysisRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def find(self, meeting_id, audio_id, source_hash, profile_hash):
        try:
            with self.sessions() as session:
                row = session.scalar(
                    select(MeetingAnalysisRecord).where(
                        MeetingAnalysisRecord.meeting_id == meeting_id,
                        MeetingAnalysisRecord.source_audio_id == audio_id,
                        MeetingAnalysisRecord.source_hash == source_hash,
                        MeetingAnalysisRecord.profile_hash == profile_hash,
                    )
                )
                return MeetingAnalysis.model_validate(row.payload) if row else None
        except (SQLAlchemyError, ValidationError) as exc:
            raise AnalysisPersistenceError from exc

    def add_or_get(self, result, audio_id, source_hash, profile_hash):
        try:
            with self.sessions.begin() as session:
                session.add(
                    MeetingAnalysisRecord(
                        meeting_id=result.meeting_id,
                        source_audio_id=audio_id,
                        source_hash=source_hash,
                        profile_hash=profile_hash,
                        payload=result.model_dump(mode="json"),
                    )
                )
            return result
        except IntegrityError as exc:
            cached = self.find(result.meeting_id, audio_id, source_hash, profile_hash)
            if cached is not None:
                return cached
            raise AnalysisPersistenceError from exc
        except SQLAlchemyError as exc:
            raise AnalysisPersistenceError from exc
