from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base
from app.meetings.models import now

STAGES = (
    "preprocessing",
    "transcribing",
    "diarizing",
    "canonicalizing",
    "resolving_speakers",
    "analyzing",
    "exporting",
)


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_id: UUID
    # A completed run is reused unless the caller explicitly requests a refresh.
    refresh: bool = False
    export_formats: list[Literal["docx", "pdf"]] = Field(
        default_factory=lambda: ["docx", "pdf"], min_length=1, max_length=2
    )


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    meeting_id: UUID
    media_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    stage: str | None
    steps: dict[str, str]
    export_formats: list[Literal["docx", "pdf"]]
    exports: list[dict]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ProcessingRun(Base):
    __tablename__ = "meeting_processing_runs"
    # One current attempt per meeting; id changes on retry. Old deliveries cannot claim it.
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), primary_key=True)
    id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    media_id: Mapped[UUID] = mapped_column(ForeignKey("media_assets.id"))
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str | None] = mapped_column(String(30))
    steps: Mapped[dict] = mapped_column(JSON)
    export_formats: Mapped[list] = mapped_column(JSON)
    exports: Mapped[list] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
