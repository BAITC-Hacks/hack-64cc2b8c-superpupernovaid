from typing import Protocol

from app.audio.models import NormalizedAudio
from app.speech.models import DiarizationResult, TranscriptionResult


class SpeechRecognizer(Protocol):
    async def transcribe(self, audio: NormalizedAudio) -> TranscriptionResult: ...


class SpeakerDiarizer(Protocol):
    async def diarize(self, audio: NormalizedAudio) -> DiarizationResult: ...
