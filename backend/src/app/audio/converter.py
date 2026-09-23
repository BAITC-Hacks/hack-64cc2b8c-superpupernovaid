from dataclasses import dataclass
from typing import BinaryIO, Protocol

from app.audio.config import AudioProcessingConfig


@dataclass(frozen=True)
class ConvertedAudio:
    sample_rate: int
    channels: int
    codec: str
    format: str
    duration_seconds: float


class AudioConverter(Protocol):
    def convert(
        self, source: BinaryIO, destination: BinaryIO, config: AudioProcessingConfig
    ) -> ConvertedAudio: ...
