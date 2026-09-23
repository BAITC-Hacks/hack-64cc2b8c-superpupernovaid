import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.audio.models import NormalizedAudio
from app.canonicalization.repository import CanonicalTranscriptRecord
from app.entrypoints.api import app
from app.infrastructure.database import Base
from app.intelligence.models import MeetingAnalysis
from app.media.models import MediaAsset
from app.media.storage import LocalMediaStorage
from app.meetings.models import Meeting, Participant
from app.protocols.dependencies import get_export_service, get_protocol_loader
from app.protocols.docx import DocxProtocolRenderer
from app.protocols.errors import MeetingProtocolNotReadyError
from app.protocols.loader import ProtocolLoader
from app.protocols.repository import ExportRepository
from app.protocols.service import ProtocolExportService
from app.speech.models import AttributedTranscript
from app.speech.repository import TranscriptRecord


@pytest.fixture
def database(tmp_path, protocol):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "api.sqlite"), connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    media_id, audio_id = uuid4(), uuid4()
    original = AttributedTranscript(
        source_audio_id=audio_id,
        segments=[
            {
                "id": "seg_abc",
                "start": 12,
                "end": 13,
                "speaker_id": "SPEAKER_00",
                "text": "Точный оригинал.",
            }
        ],
    )
    with Session(engine) as s, s.begin():
        s.add(Meeting(id=protocol.meeting_id, title=protocol.title))
        s.flush()
        s.add(
            MediaAsset(
                id=media_id,
                meeting_id=protocol.meeting_id,
                original_filename="test.wav",
                media_type="audio",
                storage_key="source",
                size_bytes=100,
                container="wav",
                status="uploaded",
            )
        )
        s.flush()
        s.add(
            NormalizedAudio(
                id=audio_id,
                source_media_id=media_id,
                config_hash="a" * 64,
                storage_key="wav",
                sample_rate=16000,
                channels=1,
                codec="pcm_s16le",
                format="wav",
                duration_seconds=13,
                size_bytes=416044,
                sha256="b" * 64,
            )
        )
        s.flush()
        s.add(
            TranscriptRecord(
                id=protocol.source_transcript_id,
                source_audio_id=audio_id,
                profile_hash="c" * 64,
                payload=original.model_dump(mode="json"),
            )
        )
        s.flush()
        s.add(
            Participant(
                meeting_id=protocol.meeting_id,
                transcript_id=protocol.source_transcript_id,
                speaker_id="SPEAKER_00",
                display_name="Әлия",
            )
        )
    yield engine, original
    engine.dispose()


def publish(engine, protocol):
    with Session(engine) as s, s.begin():
        s.add(
            MeetingAnalysis(
                transcript_id=protocol.source_transcript_id, summary="Сохранённое резюме."
            )
        )


def test_loader_requires_analysis_and_matches_canonical_source(database, protocol):
    engine, original = database
    loader = ProtocolLoader(engine)
    with pytest.raises(MeetingProtocolNotReadyError):
        loader.load(protocol.meeting_id)
    publish(engine, protocol)
    ready = loader.load(protocol.meeting_id)
    assert ready.transcript[0].original_text == "Точный оригинал."
    assert ready.transcript[0].canonical_text is None
    assert ready.transcript[0].participant_name == "Әлия"
    payload = {
        "source_audio_id": str(original.source_audio_id),
        "canonical_language": "ru",
        "segments": [
            {
                "id": "seg_abc",
                "start": 12,
                "end": 13,
                "speaker_id": "SPEAKER_00",
                "original_text": "Точный оригинал.",
                "canonical_text": "Готовый канонический текст.",
            }
        ],
    }
    with Session(engine) as s, s.begin():
        s.add(
            CanonicalTranscriptRecord(
                source_audio_id=original.source_audio_id,
                source_hash="stale",
                profile_hash="d" * 64,
                payload=payload,
            )
        )
    assert loader.load(protocol.meeting_id).transcript[0].canonical_text is None
    with Session(engine) as s, s.begin():
        s.add(
            CanonicalTranscriptRecord(
                source_audio_id=original.source_audio_id,
                source_hash=hashlib.sha256(original.model_dump_json().encode()).hexdigest(),
                profile_hash="d" * 64,
                payload=payload,
            )
        )
    assert (
        loader.load(protocol.meeting_id).transcript[0].canonical_text
        == "Готовый канонический текст."
    )


def test_download_routes_and_missing_protocol(database, protocol, pdf_renderer, tmp_path):
    engine, _ = database
    loader = ProtocolLoader(engine)
    service = ProtocolExportService(
        {"docx": DocxProtocolRenderer(), "pdf": pdf_renderer},
        LocalMediaStorage(tmp_path / "artifacts"),
        ExportRepository(engine),
    )
    app.dependency_overrides[get_protocol_loader] = lambda: loader
    app.dependency_overrides[get_export_service] = lambda: service
    try:
        with TestClient(app) as c:
            base = f"/api/v1/meetings/{protocol.meeting_id}/exports"
            assert c.get(base + "/docx").status_code == 409
            assert c.get(f"/api/v1/meetings/{uuid4()}/exports/pdf").status_code == 404
            assert c.get(base + "/html").status_code == 422
            assert not service.storage.root.exists()
            publish(engine, protocol)
            created = c.post(base, json={"format": "docx"})
            assert created.status_code == 200, created.text
            assert "storage_key" in created.json() and "content" not in created.json()
            for format, mime in [
                ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ("pdf", "application/pdf"),
            ]:
                response = c.get(base + "/" + format)
                assert response.status_code == 200, response.text
                assert response.headers["content-type"] == mime
                assert "attachment;" in response.headers["content-disposition"]
                assert (
                    f"meeting_{protocol.meeting_id}_protocol.{format}"
                    in response.headers["content-disposition"]
                )
                assert response.content[:4] == (b"%PDF" if format == "pdf" else b"PK\x03\x04")
            assert c.post(base, json={"format": "docx"}).json()["id"] == created.json()["id"]
    finally:
        app.dependency_overrides.pop(get_protocol_loader)
        app.dependency_overrides.pop(get_export_service)
