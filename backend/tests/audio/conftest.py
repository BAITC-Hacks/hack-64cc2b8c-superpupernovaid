from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.audio.config import AudioProcessingConfig
from app.audio.converter import ConvertedAudio
from app.audio.repository import AudioRepository
from app.audio.service import AudioPreprocessor
from app.bootstrap import get_audio_preprocessor, get_media_repository
from app.entrypoints.api import app
from app.infrastructure.database import Base
from app.media.models import MediaAsset
from app.media.repository import MediaRepository
from app.media.storage import LocalMediaStorage


class FakeConverter:
    calls = 0
    error = None

    def convert(self, source, destination, config):
        self.calls += 1
        self.config = config
        assert source.read(1)
        if self.error:
            raise self.error
        destination.write(b"normalized audio bytes")
        return ConvertedAudio(config.sample_rate, config.channels, config.codec, config.format, 1.0)


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
def media_repository(engine):
    return MediaRepository(engine)


@pytest.fixture
def media(media_repository, storage):
    media_id, meeting_id = uuid4(), uuid4()
    key = f"{meeting_id}/{media_id}/source"
    storage.save(key, [b"immutable original media"], "audio/wav")
    media = MediaAsset(
        id=media_id,
        meeting_id=meeting_id,
        original_filename="source.wav",
        media_type="audio",
        mime_type="audio/wav",
        storage_key=key,
        size_bytes=24,
        duration_seconds=1,
        container="wav",
        audio_codec="pcm_s16le",
        video_codec=None,
        status="uploaded",
        created_at=datetime.now(UTC),
    )
    media_repository.add(media)
    return media


@pytest.fixture
def config():
    return AudioProcessingConfig(sample_rate=16000, channels=1, codec="pcm_s16le", format="wav")


@pytest.fixture
def converter():
    return FakeConverter()


@pytest.fixture
def repository(engine):
    return AudioRepository(engine)


@pytest.fixture
def preprocessor(storage, converter, repository, config):
    return AudioPreprocessor(storage, converter, repository, config)


@pytest.fixture
def client(media_repository, preprocessor):
    app.dependency_overrides[get_audio_preprocessor] = lambda: preprocessor
    app.dependency_overrides[get_media_repository] = lambda: media_repository
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_audio_preprocessor, None)
    app.dependency_overrides.pop(get_media_repository, None)
