from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class MediaType(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"


class MediaStatus(StrEnum):
    UPLOADED = "uploaded"
    INVALID = "invalid"


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_media_assets_positive_size"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="ck_media_assets_duration"
        ),
        CheckConstraint("media_type IN ('audio', 'video')", name="ck_media_assets_type"),
        CheckConstraint("status IN ('uploaded', 'invalid')", name="ck_media_assets_status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # Meetings have no table yet; this is an external UUID reference, not a fabricated FK.
    meeting_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(10))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    container: Mapped[str] = mapped_column(String(100))
    audio_codec: Mapped[str | None] = mapped_column(String(100))
    video_codec: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default=MediaStatus.UPLOADED)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    meeting_id: UUID
    original_filename: str
    media_type: MediaType
    mime_type: str | None
    storage_key: str
    size_bytes: int
    duration_seconds: float | None
    container: str
    audio_codec: str | None
    video_codec: str | None
    status: MediaStatus
    created_at: datetime


class MediaErrorResponse(BaseModel):
    detail: dict[str, str]
