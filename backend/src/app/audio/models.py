from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class NormalizedAudio(Base):
    __tablename__ = "normalized_audio"
    __table_args__ = (
        UniqueConstraint("source_media_id", "config_hash", name="uq_audio_source_config"),
        CheckConstraint("size_bytes > 0 AND duration_seconds > 0", name="ck_audio_nonempty"),
        CheckConstraint("sample_rate > 0 AND channels > 0", name="ck_audio_parameters"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_media_id: Mapped[UUID] = mapped_column(ForeignKey("media_assets.id"))
    config_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    sample_rate: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(16))
    duration_seconds: Mapped[float] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class NormalizedAudioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_media_id: UUID
    storage_key: str
    sample_rate: int
    channels: int
    codec: str
    format: str
    duration_seconds: float
    size_bytes: int
    sha256: str
    config_hash: str
    created_at: datetime
