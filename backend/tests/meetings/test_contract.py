from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool

from app.entrypoints.api import app
from app.infrastructure.database import Base
from app.meetings.models import ChangeAudit, RecordingConsent
from app.meetings.repository import MeetingRepository, get_meetings
from app.tasks.repository import TaskRepository, get_tasks


@pytest.fixture
def workspace():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    meetings = MeetingRepository(engine)
    tasks = TaskRepository(engine)
    app.dependency_overrides[get_meetings] = lambda: meetings
    app.dependency_overrides[get_tasks] = lambda: tasks
    from app.protocols.dependencies import get_protocol_loader
    from app.protocols.loader import ProtocolLoader

    app.dependency_overrides[get_protocol_loader] = lambda: ProtocolLoader(engine)
    with TestClient(app) as client:
        yield client, meetings
    app.dependency_overrides.pop(get_meetings)
    app.dependency_overrides.pop(get_tasks)
    app.dependency_overrides.pop(get_protocol_loader)
    engine.dispose()


def create(client, title="Meeting", consent=True):
    response = client.post(
        "/api/v1/meetings", json={"title": title, "recording_consent_confirmed": consent}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_creation_consent_patch_and_no_fake_results(workspace):
    c, repo = workspace
    ident = create(c)
    result = c.get(f"/api/v1/meetings/{ident}/result").json()
    assert result["meeting"]["processing_status"] == "draft"
    assert result["summary"] is None and result["participants"] == [] and result["tasks"] == []
    assert "transcript" not in result
    assert (
        c.patch(f"/api/v1/meetings/{ident}", json={"title": "Updated"}).json()["title"] == "Updated"
    )
    assert (
        c.patch(
            f"/api/v1/meetings/{ident}", json={"recording_consent_confirmed": False}
        ).status_code
        == 422
    )
    assert c.patch(f"/api/v1/meetings/{ident}", json={"title": None}).status_code == 422
    assert (
        c.post(
            "/api/v1/meetings", json={"title": "  ", "recording_consent_confirmed": True}
        ).status_code
        == 422
    )
    with repo.sessions() as s:
        assert s.scalar(select(RecordingConsent)).confirmed
        assert s.scalar(select(ChangeAudit)).action == "meeting.patch"
    assert c.get(f"/api/v1/meetings/{uuid4()}").status_code == 404
    assert c.post(f"/api/v1/meetings/{ident}/exports", json={"format": "docx"}).status_code == 409
    assert c.post(f"/api/v1/meetings/{ident}/analyze").status_code == 501


def test_cursor_and_status_filter(workspace):
    c, _ = workspace
    ids = {create(c, str(i)) for i in range(3)}
    first = c.get("/api/v1/meetings?limit=2&status=draft").json()
    second = c.get("/api/v1/meetings", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert {x["id"] for x in first["items"] + second["items"]} == ids
    assert second["next_cursor"] is None
    assert c.get("/api/v1/meetings?cursor=bad").status_code == 422
    assert c.get("/api/v1/meetings?limit=10000").status_code == 422


def test_tasks_deadline_filters_patch_and_cross_meeting_assignment(workspace):
    c, repo = workspace
    ident = create(c)
    due = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    task = c.post(
        f"/api/v1/meetings/{ident}/tasks", json={"text": "Prepare plan", "due_at": due}
    ).json()
    assert task["status"] == "overdue"
    assert len(c.get("/api/v1/tasks?status=overdue&q=plan").json()["items"]) == 1
    assert (
        c.patch(f"/api/v1/tasks/{task['id']}", json={"status": "completed"}).json()["status"]
        == "completed"
    )
    assert c.get("/api/v1/tasks?status=overdue").json()["items"] == []
    assert (
        c.patch(
            f"/api/v1/tasks/{task['id']}", json={"due_at": None, "status": "in_progress"}
        ).json()["due_at"]
        is None
    )
    assert c.patch(f"/api/v1/tasks/{task['id']}", json={"status": "overdue"}).status_code == 422
    assert (
        c.patch(f"/api/v1/tasks/{task['id']}", json={"assignee_id": str(uuid4())}).status_code
        == 422
    )
    assert (
        c.post(
            f"/api/v1/meetings/{ident}/tasks",
            json={"text": "x", "source_segment_ids": [str(uuid4())]},
        ).status_code
        == 422
    )
    with repo.sessions() as s:
        assert len(list(s.scalars(select(ChangeAudit)))) == 3


def seed_transcript(repo, ident):
    from uuid import UUID

    from app.audio.models import NormalizedAudio
    from app.media.models import MediaAsset
    from app.speech.models import AttributedTranscript, AttributedTranscriptSegment
    from app.speech.repository import SpeechRepository

    media_id, audio_id, segment_id = uuid4(), uuid4(), uuid4()
    with repo.sessions.begin() as s:
        s.add(
            MediaAsset(
                id=media_id,
                meeting_id=UUID(ident),
                original_filename="sample.wav",
                media_type="audio",
                storage_key=str(media_id),
                size_bytes=32044,
                duration_seconds=1,
                container="wav",
                audio_codec="pcm_s16le",
                status="uploaded",
            )
        )
        s.flush()
        s.add(
            NormalizedAudio(
                id=audio_id,
                source_media_id=media_id,
                config_hash="a" * 64,
                storage_key=str(audio_id),
                sample_rate=16000,
                channels=1,
                codec="pcm_s16le",
                format="wav",
                duration_seconds=1,
                size_bytes=32044,
                sha256="b" * 64,
            )
        )
    result = AttributedTranscript(
        source_audio_id=audio_id,
        segments=[
            AttributedTranscriptSegment(
                id="seg_" + segment_id.hex, start=0, end=0.5, speaker_id="SPEAKER_00", text="Hello"
            ),
            AttributedTranscriptSegment(
                id=str(uuid4()), start=0.5, end=1, speaker_id="SPEAKER_01", text="World"
            ),
        ],
    )
    SpeechRepository(repo.sessions.kw["bind"]).add_or_get(result, "c" * 64)
    return media_id, audio_id, segment_id


def test_transcript_participants_sources_and_processing(workspace):
    c, repo = workspace
    ident = create(c)
    media_id, audio_id, segment_id = seed_transcript(repo, ident)
    result = c.get(f"/api/v1/meetings/{ident}/result").json()
    p = result["participants"][0]
    assert p["speech_share"] == 0.5
    assert (
        c.patch(
            f"/api/v1/meetings/{ident}/participants/{p['speaker_id']}",
            json={"display_name": "Айдана"},
        ).json()["display_name"]
        == "Айдана"
    )
    page = c.get(f"/api/v1/meetings/{ident}/transcript?limit=1").json()
    assert page["items"][0]["started_at_ms"] == 0 and page["items"][0]["confidence"] is None
    assert (
        c.get(
            f"/api/v1/meetings/{ident}/transcript",
            params={"cursor": page["next_cursor"], "q": "different"},
        ).status_code
        == 409
    )
    assert (
        c.get(
            f"/api/v1/meetings/{ident}/transcript", params={"cursor": page["next_cursor"]}
        ).json()["items"][0]["text"]
        == "World"
    )
    task = c.post(
        f"/api/v1/meetings/{ident}/tasks",
        json={"text": "Prepare", "source_segment_ids": [str(segment_id)], "assignee_id": p["id"]},
    )
    assert task.status_code == 201, task.text
    other = create(c)
    assert (
        c.post(
            f"/api/v1/meetings/{other}/tasks", json={"text": "x", "assignee_id": p["id"]}
        ).status_code
        == 422
    )
    from app.meetings.progress import ProcessingTracker

    tracker = ProcessingTracker(repo.sessions.kw["bind"])
    tracker.update(media_id, "diarizing", "completed")
    state = c.get(f"/api/v1/meetings/{ident}/processing").json()
    assert state["status"] == "analyzing"
    assert state["steps"][-1]["status"] == "pending"
    tracker.update(media_id, "transcribing", "failed")
    assert c.get(f"/api/v1/meetings/{ident}/processing").json()["status"] == "failed"


def test_analysis_publication_validates_sources_and_is_atomic(workspace):
    from uuid import UUID

    from fastapi import HTTPException

    from app.intelligence.repository import AnalysisInput, AnalysisRepository
    from app.meetings.repository import latest_transcript

    c, repo = workspace
    ident = create(c)
    _, _, segment_id = seed_transcript(repo, ident)
    with repo.sessions() as s:
        record_id = latest_transcript(s, UUID(ident)).id
    publisher = AnalysisRepository(repo.sessions.kw["bind"])
    bad = AnalysisInput(
        transcript_id=record_id,
        summary="Summary",
        tasks=[{"text": "Task", "source_segment_ids": [uuid4()]}],
    )
    with pytest.raises(HTTPException):
        publisher.publish(UUID(ident), bad)
    assert c.get(f"/api/v1/meetings/{ident}/result").json()["summary"] is None
    good = AnalysisInput(
        transcript_id=record_id,
        summary="Summary",
        decisions=[{"text": "Decision", "source_segment_ids": [segment_id]}],
        tasks=[{"text": "Task", "source_segment_ids": [segment_id]}],
    )
    publisher.publish(UUID(ident), good)
    result = c.get(f"/api/v1/meetings/{ident}/result").json()
    assert result["meeting"]["processing_status"] == "ready"
    assert result["summary"] == "Summary" and len(result["tasks"]) == 1
    with pytest.raises(HTTPException):
        publisher.publish(UUID(ident), good)
    assert len(c.get(f"/api/v1/meetings/{ident}/tasks").json()["items"]) == 1
