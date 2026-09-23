from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.speech.models import TimeSegment


class CanonicalizedSegmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    canonical_text: str
    uncertain: bool

    @field_validator("canonical_text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Canonical text must not be blank")
        return value


class CanonicalizationBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segments: list[CanonicalizedSegmentOutput]


class CanonicalTranscriptSegment(TimeSegment):
    id: str
    speaker_id: str = Field(pattern=r"^(SPEAKER_[0-9]{2,}|UNKNOWN)$")
    original_text: str
    canonical_text: str = Field(min_length=1)
    canonicalization_uncertain: bool = False


class CanonicalTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_audio_id: UUID
    canonical_language: str
    segments: list[CanonicalTranscriptSegment]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({s.id for s in self.segments}) != len(self.segments):
            raise ValueError("Canonical transcript segment IDs must be unique")
        return self
