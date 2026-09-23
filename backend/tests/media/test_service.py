from contextlib import contextmanager
from io import BytesIO
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.application.ports import FileStorageError
from app.media.errors import (
    InvalidMediaError,
    MediaPersistenceError,
    MediaProbeError,
    MediaStorageError,
    MediaTooLargeError,
    UnsupportedMediaError,
)
from app.media.models import MediaAsset, MediaType
from app.media.probe import MediaMetadata
from app.media.service import MediaService
from app.media.validation import CHUNK_SIZE, SUPPORTED_FORMATS


@pytest.mark.parametrize(
    "kind,container,audio,video",
    [
        (MediaType.AUDIO, "wav", "pcm_s16le", None),
        (MediaType.VIDEO, "mov", "aac", "h264"),
        (MediaType.VIDEO, "matroska", None, "vp9"),
    ],
)
def test_persist_audio_video(
    service, repository, storage, probe, meeting_id, source, kind, container, audio, video
):
    probe.metadata = MediaMetadata(kind, container, 120.5, None, audio, video)
    asset = service.ingest(meeting_id, "recording.bin", source)
    found = repository.get(meeting_id, asset.id)
    assert found.media_type == kind
    assert found.audio_codec == audio
    assert found.video_codec == video
    assert found.status == "uploaded"
    assert found.size_bytes == len(b"test-media-bytes")
    assert found.duration_seconds == 120.5
    with storage.open(found.storage_key) as stored:
        assert stored.read() == b"test-media-bytes"


def test_safe_unique_storage_names(service, meeting_id, source):
    first = service.ingest(meeting_id, "../../../../secret.wav", source)
    second = service.ingest(meeting_id, r"C:\private\secret.wav", BytesIO(b"second"))
    assert first.original_filename == second.original_filename == "secret.wav"
    assert first.storage_key != second.storage_key
    assert first.storage_key == f"{meeting_id}/{first.id}/source"
    UUID(first.storage_key.split("/")[1])
    assert "secret" not in first.storage_key


@pytest.mark.parametrize("error", [UnsupportedMediaError, InvalidMediaError, MediaProbeError])
def test_probe_failure_cleans_original(
    service, probe, storage, repository, meeting_id, source, error
):
    probe.error = error()
    with pytest.raises(error):
        service.ingest(meeting_id, "file.wav", source)
    assert not list(storage.root.rglob("source"))
    with repository.sessions() as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0


@pytest.mark.parametrize(
    "data,limit,error", [(b"", 8, InvalidMediaError), (b"12345", 4, MediaTooLargeError)]
)
def test_empty_and_oversize_cleanup(service, storage, probe, meeting_id, data, limit, error):
    service.max_bytes = limit
    with pytest.raises(error):
        service.ingest(meeting_id, "file.wav", BytesIO(data))
    assert not list(storage.root.rglob("source"))
    assert probe.calls == 0


def test_exact_limit_allowed(service, meeting_id):
    service.max_bytes = 4
    assert service.ingest(meeting_id, "a.wav", BytesIO(b"1234")).size_bytes == 4


def test_configured_container_restriction(service, storage, meeting_id, source):
    service.allowed_formats = frozenset({"mp3"})
    with pytest.raises(UnsupportedMediaError):
        service.ingest(meeting_id, "a.mp3", source)
    assert not list(storage.root.rglob("source"))


def test_reads_bounded_chunks(service, meeting_id):
    class BoundedReader(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= CHUNK_SIZE
            return super().read(size)

    data = b"a" * (2 * CHUNK_SIZE + 17)
    asset = service.ingest(meeting_id, "large.wav", BoundedReader(data))
    assert asset.size_bytes == len(data)


def test_service_uses_replaceable_storage(repository, probe, meeting_id, source):
    class MemoryStorage:
        def __init__(self):
            self.data = {}
            self.opened = False

        def save(self, key, chunks, content_type):
            self.data[key] = b"".join(chunks)
            return len(self.data[key])

        @contextmanager
        def open(self, key):
            self.opened = True
            yield BytesIO(self.data[key])

        def delete(self, key):
            self.data.pop(key, None)

    memory = MemoryStorage()
    service = MediaService(memory, probe, repository, 100, SUPPORTED_FORMATS)
    asset = service.ingest(meeting_id, "a.wav", source)
    assert memory.opened
    assert asset.storage_key in memory.data


def test_database_failure_removes_original(
    service, repository, storage, meeting_id, source, monkeypatch
):
    def unavailable():
        raise OperationalError("INSERT", {}, RuntimeError("secret db connection details"))

    monkeypatch.setattr(repository.sessions, "begin", unavailable)
    with pytest.raises(MediaPersistenceError):
        service.ingest(meeting_id, "a.wav", source)
    assert not list(storage.root.rglob("source"))


def test_storage_error_translated(service, storage, meeting_id, source, monkeypatch):
    def unavailable(*args):
        raise FileStorageError("private/path")

    monkeypatch.setattr(storage, "save", unavailable)
    with pytest.raises(MediaStorageError):
        service.ingest(meeting_id, "a.wav", source)


def test_cleanup_failure_does_not_hide_original_error(
    service, storage, probe, meeting_id, source, monkeypatch, caplog
):
    probe.error = InvalidMediaError()

    def unavailable(*args):
        raise FileStorageError()

    monkeypatch.setattr(storage, "delete", unavailable)
    with pytest.raises(InvalidMediaError):
        service.ingest(meeting_id, "a.wav", source)
    assert "media_cleanup_failed" in caplog.text


def test_logs_contain_metadata_not_content(service, meeting_id, source, caplog):
    with caplog.at_level("INFO", logger="app.media.service"):
        asset = service.ingest(meeting_id, "file.wav", source)
    assert str(asset.id) in caplog.text and str(meeting_id) in caplog.text
    assert "size_bytes=" in caplog.text and "duration=" in caplog.text
    assert "test-media-bytes" not in caplog.text
