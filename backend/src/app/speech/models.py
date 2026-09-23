from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Segment end must be after start")
        return self


class TranscriptionSegment(TimeSegment):
    text: str = Field(min_length=1)


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[TranscriptionSegment]


class SpeakerSegment(TimeSegment):
    speaker_id: str = Field(pattern=r"^SPEAKER_[0-9]{2,}$")


class DiarizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[SpeakerSegment]


class AttributedTranscriptSegment(TranscriptionSegment):
    id: str
    speaker_id: str = Field(pattern=r"^(SPEAKER_[0-9]{2,}|UNKNOWN)$")


class AttributedTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_audio_id: UUID
    segments: list[AttributedTranscriptSegment]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({s.id for s in self.segments}) != len(self.segments):
            raise ValueError("Transcript segment IDs must be unique")
        return self
