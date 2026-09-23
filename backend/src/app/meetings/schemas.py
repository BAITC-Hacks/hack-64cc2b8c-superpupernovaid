from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Status = Literal[
    "draft",
    "uploaded",
    "preprocessing",
    "transcribing",
    "diarizing",
    "analyzing",
    "ready",
    "failed",
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MeetingCreate(Input):
    title: str = Field(min_length=1, max_length=255)
    scheduled_at: AwareDatetime | None = None
    language_hint: Literal["ru", "kk", "mixed", "auto"] = "ru"
    expected_participant_count: int | None = Field(default=None, ge=1, le=1000)
    recording_consent_confirmed: bool


class MeetingPatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    scheduled_at: AwareDatetime | None = None
    language_hint: Literal["ru", "kk", "mixed", "auto"] | None = None
    expected_participant_count: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def nonnull(self):
        for key in ("title", "language_hint"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class MeetingView(BaseModel):
    id: UUID
    title: str
    scheduled_at: datetime | None
    started_at: datetime | None = None
    duration_seconds: float | None
    language_hint: str
    language_detected: list[str] = []
    expected_participant_count: int | None
    recording_consent_confirmed: bool | None
    processing_status: Status
    created_at: datetime
    updated_at: datetime


class MeetingPage(BaseModel):
    items: list[MeetingView]
    next_cursor: str | None


class ParticipantPatch(Input):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)


class ParticipantView(BaseModel):
    id: UUID
    speaker_id: str
    display_name: str | None
    speech_share: float | None


class TranscriptSegmentView(BaseModel):
    id: UUID
    started_at_ms: int
    ended_at_ms: int
    speaker_id: str
    text: str
    confidence: float | None = None
    language: str | None = None


class TranscriptPage(BaseModel):
    items: list[TranscriptSegmentView]
    next_cursor: str | None


class StepView(BaseModel):
    stage: str
    status: Literal["pending", "running", "completed", "failed", "unavailable"]
    progress: int | None
    message: str
    updated_at: datetime


class ProcessingView(BaseModel):
    meeting_id: UUID
    media_id: UUID | None
    status: Status
    steps: list[StepView]
    updated_at: datetime
