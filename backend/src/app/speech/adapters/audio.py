import hashlib
import wave
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.application.ports import FileStorage
from app.audio.models import NormalizedAudio
from app.speech.errors import SpeechAudioError


@dataclass(frozen=True)
class AudioWindow:
    path: Path
    offset: float
    keep_start: float
    keep_end: float


class AudioFiles:
    """Bounded storage reads; no samples in the public NormalizedAudio contract."""

    def __init__(self, storage: FileStorage, max_duration=14400, max_decoded_bytes=536870912):
        self.storage = storage
        self.max_duration = max_duration
        self.max_decoded_bytes = max_decoded_bytes

    def validate_metadata(self, audio: NormalizedAudio, *, diarization=True):
        if (audio.format, audio.codec, audio.sample_rate, audio.channels) != (
            "wav",
            "pcm_s16le",
            16000,
            1,
        ) or not 0 < audio.duration_seconds <= self.max_duration:
            raise SpeechAudioError
        # Native full-recording diarizers may decode float32 and retain model features.
        # This is an admission budget for waveform only, not a total RAM/VRAM guarantee.
        if diarization and audio.duration_seconds * 16000 * 4 > self.max_decoded_bytes:
            raise SpeechAudioError
        if not 0 < audio.size_bytes <= audio.duration_seconds * 32000 + 1024 * 1024:
            raise SpeechAudioError

    @contextmanager
    def local(self, audio: NormalizedAudio, *, diarization=False):
        self.validate_metadata(audio, diarization=diarization)
        with TemporaryDirectory(prefix="speech-") as folder:
            path = Path(folder) / "audio.wav"
            total, digest = 0, hashlib.sha256()
            with self.storage.open(audio.storage_key) as source, path.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    if total > audio.size_bytes:
                        raise SpeechAudioError
                    digest.update(chunk)
                    target.write(chunk)
            if total != audio.size_bytes or digest.hexdigest() != audio.sha256:
                raise SpeechAudioError
            with wave.open(str(path), "rb") as stream:
                if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (
                    16000,
                    1,
                    2,
                ) or abs(stream.getnframes() / 16000 - audio.duration_seconds) > 0.1:
                    raise SpeechAudioError
            yield path

    def windows(self, path: Path, core_seconds=25, context_seconds=2.5):
        # One reusable on-disk window; at most 1 second of PCM in Python at a time.
        with wave.open(str(path), "rb") as source:
            rate, frames = source.getframerate(), source.getnframes()
            core, context = int(core_seconds * rate), int(context_seconds * rate)
            for first in range(0, frames, core):
                last = min(frames, first + core)
                start, end = max(0, first - context), min(frames, last + context)
                window = path.parent / "window.wav"
                source.setpos(start)
                with wave.open(str(window), "wb") as output:
                    output.setparams(source.getparams())
                    remaining = end - start
                    while remaining:
                        count = min(rate, remaining)
                        data = source.readframes(count)
                        if len(data) != count * 2:
                            raise SpeechAudioError
                        output.writeframesraw(data)
                        remaining -= count
                yield AudioWindow(window, start / rate, first / rate, last / rate)
