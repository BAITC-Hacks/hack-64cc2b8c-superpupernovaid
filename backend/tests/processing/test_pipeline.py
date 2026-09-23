import asyncio
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.entrypoints.api import app as real_app  # noqa: F401 register FK models
from app.infrastructure.database import Base
from app.media.models import MediaAsset
from app.meetings.models import Meeting
from app.meetings.progress import ProcessingTracker
from app.meetings.repository import MeetingRepository
from app.processing.dependencies import get_processing_repository, get_submit_meeting_processing
from app.processing.errors import ProcessingConflict, ProcessingQueueError
from app.processing.models import ProcessRequest
from app.processing.repository import ProcessingRepository
from app.processing.router import router
from app.processing.service import MeetingProcessingService, SubmitMeetingProcessing


@pytest.fixture
def setup(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "pipeline.sqlite"))

    @event.listens_for(engine, "connect")
    def fk(c, _):
        c.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    meeting, media = uuid4(), uuid4()
    with Session(engine) as s, s.begin():
        s.add(Meeting(id=meeting, title="Тест", language_hint="ru"))
        s.flush()
        s.add(
            MediaAsset(
                id=media,
                meeting_id=meeting,
                original_filename="test.mp3",
                media_type="audio",
                storage_key="x",
                size_bytes=12,
                status="uploaded",
                container="mp3",
            )
        )
    yield engine, ProcessingRepository(engine), meeting, ProcessRequest(media_id=media)
    engine.dispose()


class FakeStages:
    def __init__(self, fail=None):
        self.calls, self.failure = [], fail

    async def step(self, name, result=None):
        self.calls.append(name)
        if self.failure == name:
            raise RuntimeError("secret transcript must not leak")
        return result

    async def validate(self, run):
        await self.step("validate")

    async def preprocess(self, run):
        return await self.step("preprocess", "audio")

    async def speech(self, run, audio):
        assert audio == "audio"
        return await self.step("speech", "transcript")

    async def canonicalize(self, run, transcript):
        assert transcript == "transcript"
        await self.step("canonicalize")

    async def speakers(self, run):
        await self.step("speakers")

    async def analyze(self, run):
        await self.step("analyze")

    async def export(self, run):
        return await self.step("export", [{"format": "docx"}, {"format": "pdf"}])


def test_order_idempotency_status_and_retry(setup):
    engine, repo, meeting, payload = setup
    run, created = repo.submit(meeting, payload)
    assert created and run.status == "queued"
    again, created = repo.submit(meeting, payload)
    assert not created and run.id == again.id
    stages = FakeStages()
    service = MeetingProcessingService(repo, stages)
    asyncio.run(service.execute(run.id))
    assert stages.calls == [
        "validate",
        "preprocess",
        "speech",
        "canonicalize",
        "speakers",
        "analyze",
        "export",
    ]
    done = repo.get(meeting)
    assert done.status == "completed" and all(s == "completed" for s in done.steps.values())
    assert MeetingRepository(engine).processing(meeting).status == "ready"
    assert len(done.exports) == 2
    asyncio.run(service.execute(run.id))
    assert len(stages.calls) == 7
    assert repo.submit(meeting, payload)[0].id == run.id
    fresh, created = repo.submit(meeting, payload.model_copy(update={"refresh": True}))
    assert created and fresh.id != run.id


def test_failure_stops_pipeline_and_retry_gets_new_attempt(setup):
    _, repo, meeting, payload = setup
    run, _ = repo.submit(meeting, payload)
    stages = FakeStages("canonicalize")
    asyncio.run(MeetingProcessingService(repo, stages).execute(run.id))
    failed = repo.get(meeting)
    assert failed.status == "failed" and failed.stage == "canonicalizing"
    assert "analyze" not in stages.calls and "export" not in stages.calls
    assert "secret" not in failed.model_dump_json()
    retry, created = repo.submit(meeting, payload)
    assert created and retry.id != run.id
    assert repo.claim(run.id) is None


def test_queue_failure_can_be_retried(setup):
    _, repo, meeting, payload = setup

    class Queue:
        def enqueue(self, ident):
            raise OSError("broker credentials")

    service = SubmitMeetingProcessing(repo, Queue(), lambda *_: None)
    with pytest.raises(ProcessingQueueError):
        service.submit(meeting, payload)
    assert repo.get(meeting).status == "failed"
    assert "credentials" not in repo.get(meeting).model_dump_json()


def test_duplicate_delivery_and_tracker_cannot_mark_ready(setup):
    engine, repo, meeting, payload = setup
    run, _ = repo.submit(meeting, payload)
    assert repo.claim(run.id)
    assert repo.claim(run.id) is None
    ProcessingTracker(engine).update(payload.media_id, "diarizing", "completed")
    assert repo.get(meeting).status == "running"
    with Session(engine) as s:
        assert s.get(Meeting, meeting).processing_status != "ready"
    with pytest.raises(ProcessingConflict):
        repo.submit(meeting, payload.model_copy(update={"export_formats": ["pdf"]}))


def test_new_recording_prevents_export_of_wrong_meeting_version(setup):
    engine, repo, meeting, payload = setup
    run, _ = repo.submit(meeting, payload)
    assert repo.claim(run.id)
    with Session(engine) as s, s.begin():
        s.add(
            MediaAsset(
                id=uuid4(),
                meeting_id=meeting,
                original_filename="new.mp3",
                media_type="audio",
                storage_key="new",
                size_bytes=12,
                status="uploaded",
                container="mp3",
            )
        )
    with pytest.raises(ProcessingConflict):
        repo.transition(run.id, "analyzing", "running")
    with pytest.raises(ProcessingConflict):
        repo.finish(run.id, [])


def test_api_returns_immediately_and_reuses_active_run(setup):
    _, repo, meeting, payload = setup
    calls = []

    class Queue:
        def enqueue(self, ident):
            calls.append(ident)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_processing_repository] = lambda: repo
    app.dependency_overrides[get_submit_meeting_processing] = lambda: SubmitMeetingProcessing(
        repo, Queue(), lambda *_: None
    )
    with TestClient(app) as c:
        url = f"/api/v1/meetings/{meeting}"
        one = c.post(url + "/process", json=payload.model_dump(mode="json"))
        two = c.post(url + "/process", json=payload.model_dump(mode="json"))
        assert one.status_code == two.status_code == 202
        assert one.json()["id"] == two.json()["id"] and len(calls) == 2
        assert calls[0] == calls[1]
        assert c.get(url + "/processing-run").json()["status"] == "queued"
        assert (
            c.post(
                url + "/process",
                json={"media_id": str(payload.media_id), "export_formats": ["html"]},
            ).status_code
            == 422
        )


def test_broker_timeout_after_claim_does_not_fail_running_attempt(setup):
    _, repo, meeting, payload = setup

    class Queue:
        def enqueue(self, ident):
            assert repo.claim(ident)
            raise TimeoutError()

    with pytest.raises(ProcessingQueueError):
        SubmitMeetingProcessing(repo, Queue(), lambda *_: None).submit(meeting, payload)
    assert repo.get(meeting).status == "running"


def test_concurrent_deliveries_only_one_executes(setup):
    _, repo, meeting, payload = setup
    run, _ = repo.submit(meeting, payload)
    stages = FakeStages()
    service = MeetingProcessingService(repo, stages)

    async def race():
        await asyncio.gather(service.execute(run.id), service.execute(run.id))

    asyncio.run(race())
    assert stages.calls.count("analyze") == 1
    assert repo.get(meeting).status == "completed"


def test_unknown_model_error_is_safe_and_no_partial_exports(setup):
    from app.intelligence.pipeline.errors import AgentOutputValidationError

    _, repo, meeting, payload = setup
    run, _ = repo.submit(meeting, payload)

    class Invalid(FakeStages):
        async def analyze(self, run):
            raise AgentOutputValidationError

    asyncio.run(MeetingProcessingService(repo, Invalid()).execute(run.id))
    failed = repo.get(meeting)
    assert failed.error_code == "meeting_agent_invalid_output"
    assert failed.stage == "analyzing" and failed.exports == []
