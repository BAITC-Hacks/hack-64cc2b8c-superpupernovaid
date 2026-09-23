import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PIPELINE_VERSION = "audio-v1-first-stream-preserve-timeline"


class AudioProcessingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    sample_rate: int = Field(ge=8000, le=192000)
    channels: int = Field(ge=1, le=2)
    codec: Literal["pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "flac"]
    format: Literal["wav", "flac"]

    @model_validator(mode="after")
    def compatible_codec(self):
        if (self.format == "flac") != (self.codec == "flac"):
            raise ValueError("Use a PCM codec for WAV, or flac codec for FLAC")
        return self

    @property
    def fingerprint(self) -> str:
        data = {**self.model_dump(), "pipeline": PIPELINE_VERSION}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    @property
    def mime_type(self) -> str:
        return {"wav": "audio/wav", "flac": "audio/flac"}[self.format]
