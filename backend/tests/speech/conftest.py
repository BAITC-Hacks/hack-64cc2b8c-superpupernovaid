import hashlib
import io
import wave
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.audio.models import NormalizedAudio
from app.audio.repository import AudioRepository
from app.config import Settings
from app.infrastructure.database import Base
from app.media.models import MediaAsset
from app.media.repository import MediaRepository
from app.media.storage import LocalMediaStorage
from app.speech.alignment import SpeakerTranscriptAligner
from app.speech.models import DiarizationResult, TranscriptionResult
from app.speech.repository import SpeechRepository
from app.speech.service import SpeechService


class FakeSpeechRecognizer:
    calls = 0

    async def transcribe(self, audio):
        self.calls += 1
        return TranscriptionResult(segments=[{"start": 0, "end": 1, "text": "Привет"}])


class FakeSpeakerDiarizer:
    calls = 0

    async def diarize(self, audio):
        self.calls += 1
        return DiarizationResult(segments=[{"start": 0, "end": 1, "speaker_id": "SPEAKER_00"}])


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def storage(tmp_path):
    return LocalMediaStorage(tmp_path / "media")


@pytest.fixture
def audio(engine, storage):
    media_id, meeting_id, audio_id = uuid4(), uuid4(), uuid4()
    media = MediaAsset(
        id=media_id,
        meeting_id=meeting_id,
        original_filename="test.wav",
        media_type="audio",
        mime_type="audio/wav",
        storage_key=f"{meeting_id}/{media_id}/source",
        size_bytes=1,
        duration_seconds=1,
        container="wav",
        audio_codec="pcm_s16le",
        status="uploaded",
        created_at=datetime.now(UTC),
    )
    MediaRepository(engine).add(media)
    content = io.BytesIO()
    with wave.open(content, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00" * 32000)
    data = content.getvalue()
    key = f"{meeting_id}/{media_id}/processed/{audio_id}/speech_input.wav"
    storage.save(key, [data], "audio/wav")
    result = NormalizedAudio(
        id=audio_id,
        source_media_id=media_id,
        storage_key=key,
        sample_rate=16000,
        channels=1,
        codec="pcm_s16le",
        format="wav",
        duration_seconds=1,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=datetime.now(UTC),
        config_hash=Settings(_env_file=None).audio_processing_config.fingerprint,
    )
    return AudioRepository(engine).add_or_get(result)


@pytest.fixture
def service(engine):
    return SpeechService(
        FakeSpeechRecognizer(),
        FakeSpeakerDiarizer(),
        SpeakerTranscriptAligner(),
        SpeechRepository(engine),
        "a" * 64,
    )
