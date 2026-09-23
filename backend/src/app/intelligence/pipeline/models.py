from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.canonicalization.models import CanonicalTranscript, CanonicalTranscriptSegment

Text = Annotated[str, Field(min_length=1)]
Sources = Annotated[list[Text], Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MeetingContext(Contract):
    meeting_id: UUID
    title: Text | None = None
    started_at: datetime | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Expected an IANA timezone") from exc
        return value

    @field_validator("started_at")
    @classmethod
    def aware_datetime(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("started_at must include its UTC offset")
        return value


class Participant(Contract):
    id: Text
    name: Text
    role: Text | None = None


class SpeakerResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class SpeakerMapping(Contract):
    speaker_id: str = Field(pattern=r"^(SPEAKER_[0-9]{2,}|UNKNOWN)$")
    participant_id: Text | None = None
    status: SpeakerResolutionStatus = SpeakerResolutionStatus.UNRESOLVED
    evidence_segment_ids: list[Text] = Field(default_factory=list)
    candidate_participant_ids: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_resolution(self):
        if len(set(self.evidence_segment_ids)) != len(self.evidence_segment_ids):
            raise ValueError("Duplicate mapping evidence")
        if len(set(self.candidate_participant_ids)) != len(self.candidate_participant_ids):
            raise ValueError("Duplicate mapping candidates")
        if self.status == SpeakerResolutionStatus.RESOLVED:
            if self.participant_id is None or not self.evidence_segment_ids:
                raise ValueError("Resolved mapping requires participant and evidence")
            if self.candidate_participant_ids or self.speaker_id == "UNKNOWN":
                raise ValueError("Resolved mapping cannot be ambiguous or UNKNOWN")
        elif self.participant_id is not None:
            raise ValueError("Unresolved/conflict mapping cannot choose a participant")
        if self.status == SpeakerResolutionStatus.CONFLICT and (
            len(self.candidate_participant_ids) < 2 or not self.evidence_segment_ids
        ):
            raise ValueError("Conflict requires at least two candidates and evidence")
        return self


class SpeakerResolutionResult(Contract):
    mappings: list[SpeakerMapping]


class SpeakerResolutionContext(Contract):
    speaker_id: str
    participants: list[Participant]
    segments: list[CanonicalTranscriptSegment]
    context_truncated: bool


class SpeakerMappingArtifact(Contract):
    mappings: list[SpeakerMapping]
    context_limited_speakers: list[str] = Field(default_factory=list)
    manual_override_speakers: list[str] = Field(default_factory=list)


class MeetingIntelligenceInput(Contract):
    meeting: MeetingContext
    transcript: CanonicalTranscript
    participants: list[Participant] = Field(default_factory=list)
    speaker_mapping: list[SpeakerMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        ids = [p.id for p in self.participants]
        speakers = [m.speaker_id for m in self.speaker_mapping]
        if len(ids) != len(set(ids)) or len(speakers) != len(set(speakers)):
            raise ValueError("Participant IDs and mapping speaker IDs must be unique")
        known_speakers = {s.speaker_id for s in self.transcript.segments}
        segment_ids = {s.id for s in self.transcript.segments}
        for mapping in self.speaker_mapping:
            if mapping.participant_id is not None and mapping.participant_id not in ids:
                raise ValueError("Unknown participant in speaker mapping")
            if not set(mapping.candidate_participant_ids) <= set(ids):
                raise ValueError("Unknown participant candidate")
            if not set(mapping.evidence_segment_ids) <= segment_ids:
                raise ValueError("Unknown mapping evidence")
            if mapping.speaker_id not in known_speakers:
                raise ValueError("Speaker mapping must reference a transcript speaker")
        return self


class GroundedText(Contract):
    text: Text
    source_segment_ids: Sources


class CandidateActionItem(Contract):
    task: Text
    assignee_text: Text | None = None
    assignee_participant_id: Text | None = None
    deadline_text: Text | None = None
    source_segment_ids: Sources
    unresolved: bool = False


class ChunkAnalysis(Contract):
    action_items: list[CandidateActionItem]
    decisions: list[GroundedText]
    important_facts: list[GroundedText]
    unresolved_references: list[GroundedText]


class ResolvedActionCandidate(Contract):
    task: Text
    assignee_participant_id: Text | None
    assignee_name: Text | None
    deadline: date | None
    deadline_text: Text | None
    deadline_kind: Literal["absolute", "relative", "unspecified"]
    source_segment_ids: Sources
    needs_review: bool


class ResolvedMeetingFacts(Contract):
    action_items: list[ResolvedActionCandidate]
    decisions: list[GroundedText]
    unresolved_items: list[GroundedText]


class MeetingSummary(Contract):
    # Ground claims internally so review can fetch only their actual evidence.
    claims: list[GroundedText]
    topics: list[GroundedText]
    key_points: list[GroundedText]
    unresolved_questions: list[GroundedText]


class ActionItem(Contract):
    id: UUID
    task: Text
    assignee_participant_id: Text | None
    assignee_name: Text | None
    deadline: date | None
    deadline_text: Text | None
    source_segment_ids: Sources
    needs_review: bool = False


class ReviewIssue(Contract):
    entity_type: Literal["action_item", "decision", "summary", "topic", "key_point", "question"]
    entity_index: int = Field(ge=0)
    field: Text | None
    reason: Text
    source_segment_ids: Sources


class ReviewResult(Contract):
    approved: bool
    issues: list[ReviewIssue]

    @model_validator(mode="after")
    def consistent(self):
        if self.approved != (not self.issues):
            raise ValueError("approved must agree with issues")
        return self


class MeetingAnalysis(Contract):
    meeting_id: UUID
    summary: str
    summary_claims: list[GroundedText] = Field(default_factory=list)
    topics: list[str]
    key_points: list[str]
    decisions: list[GroundedText]
    action_items: list[ActionItem]
    unresolved_questions: list[str]
    review_required: bool = False
    review_issues: list[ReviewIssue] = Field(default_factory=list)
    speaker_mapping: SpeakerMappingArtifact = Field(
        default_factory=lambda: SpeakerMappingArtifact(mappings=[])
    )


class ExtractionInput(Contract):
    targets: list[CanonicalTranscriptSegment]
    context_only: list[CanonicalTranscriptSegment]
    participants: list[Participant] = Field(default_factory=list)
    speaker_mapping: list[SpeakerMapping] = Field(default_factory=list)


class ResolverInput(Contract):
    meeting: MeetingContext
    participants: list[Participant]
    speaker_mapping: list[SpeakerMapping]
    chunks: list[ChunkAnalysis]
    evidence: list[CanonicalTranscriptSegment]


class SummaryInput(Contract):
    meeting: MeetingContext
    resolved: ResolvedMeetingFacts
    chunks: list[ChunkAnalysis]
    evidence: list[CanonicalTranscriptSegment]


class ReviewEntity(Contract):
    entity_type: Literal["action_item", "decision", "summary", "topic", "key_point", "question"]
    entity_index: int
    content: ResolvedActionCandidate | GroundedText


class ReviewInput(Contract):
    meeting: MeetingContext
    participants: list[Participant]
    speaker_mapping: list[SpeakerMapping]
    entities: list[ReviewEntity]
    evidence: list[CanonicalTranscriptSegment]


class AnalyzeRequest(Contract):
    media_id: UUID
    title: Text | None = None
    started_at: datetime | None = None
    timezone: str | None = None
    participants: list[Participant] = Field(default_factory=list, max_length=500)
    speaker_mapping: list[SpeakerMapping] = Field(default_factory=list, max_length=500)
