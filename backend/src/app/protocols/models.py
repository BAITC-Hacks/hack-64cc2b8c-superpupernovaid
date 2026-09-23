from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ExportFormat = Literal["docx", "pdf"]
TextMode = Literal["canonical", "original"]
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProtocolParticipant(Snapshot):
    speaker_id: str
    participant_name: str | None = None


class ProtocolDecision(Snapshot):
    text: str
    source_segment_ids: tuple[str, ...] = ()


class ProtocolAction(Snapshot):
    text: str
    assignee: str | None = None
    deadline: str | None = None
    status: str | None = None
    source_segment_ids: tuple[str, ...] = ()


class ProtocolSegment(Snapshot):
    id: str
    start: float = Field(ge=0, allow_inf_nan=False)
    speaker_id: str
    participant_name: str | None = None
    original_text: str
    canonical_text: str | None = None


class MeetingProtocol(Snapshot):
    meeting_id: UUID
    source_transcript_id: UUID
    title: str
    scheduled_at: datetime | None = None
    participants: tuple[ProtocolParticipant, ...] = ()
    summary: str | None = None
    topics: tuple[str, ...] = ()
    decisions: tuple[ProtocolDecision, ...] = ()
    action_items: tuple[ProtocolAction, ...] = ()
    transcript: tuple[ProtocolSegment, ...]


class ExportedDocument(Snapshot):
    id: UUID
    meeting_id: UUID
    format: ExportFormat
    filename: str
    storage_key: str
    size_bytes: int
    sha256: str
    protocol_hash: str
    created_at: datetime
