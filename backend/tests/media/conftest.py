from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.bootstrap import get_media_service
from app.entrypoints.api import app
from app.infrastructure.database import Base
from app.media.models import MediaType
from app.media.probe import MediaMetadata
from app.media.repository import MediaRepository
from app.media.service import MediaService
from app.media.storage import LocalMediaStorage
from app.media.validation import SUPPORTED_FORMATS


class FakeProbe:
    def __init__(self):
        self.metadata = MediaMetadata(MediaType.AUDIO, "wav", 1.0, "audio/wav", "pcm_s16le")
        self.error = None
        self.calls = 0

    def inspect(self, stream):
        self.calls += 1
        assert stream.read(1)
        if self.error:
            raise self.error
        return self.metadata


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield MediaRepository(engine)
    engine.dispose()


@pytest.fixture
def storage(tmp_path):
    return LocalMediaStorage(tmp_path / "media")


@pytest.fixture
def probe():
    return FakeProbe()


@pytest.fixture
def service(repository, storage, probe):
    return MediaService(storage, probe, repository, 4 * 1024 * 1024, SUPPORTED_FORMATS)


@pytest.fixture
def client(service):
    app.dependency_overrides[get_media_service] = lambda: service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_media_service, None)


@pytest.fixture
def meeting_id(repository):
    from app.meetings.repository import MeetingRepository
    from app.meetings.schemas import MeetingCreate
    return MeetingRepository(repository.sessions.kw["bind"]).create(
        MeetingCreate(title="Test", recording_consent_confirmed=True)
    ).id


@pytest.fixture
def source():
    return BytesIO(b"test-media-bytes")
