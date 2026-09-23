"""Offline regression tests against the actual UI + persistence boundaries."""

import asyncio
import hashlib
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonicalization.models import CanonicalTranscript
from app.canonicalization.repository import CanonicalTranscriptRecord
from app.config import Settings
from app.entrypoints.api import app
from app.intelligence.dependencies import get_analysis_coordinator
from app.intelligence.integration import AnalysisCoordinator
from app.intelligence.models import Decision, MeetingAnalysis
from app.intelligence.pipeline.dependencies import intelligence_profile, speaker_resolution_profile
from app.intelligence.pipeline.errors import ExtractionAgentError
from app.intelligence.pipeline.models import (
    ChunkAnalysis,
    GroundedText,
    MeetingSummary,
    ResolvedActionCandidate,
    ResolvedMeetingFacts,
    ReviewResult,
)
from app.intelligence.pipeline.repository import MeetingAnalysisRepository
from app.intelligence.pipeline.service import MeetingIntelligenceService
from app.intelligence.pipeline.speaker_repository import SpeakerMappingRepository
from app.intelligence.pipeline.speaker_resolution import SpeakerResolutionService
from app.intelligence.repository import AnalysisInput, AnalysisRepository, DecisionInput
from app.meetings.identifiers import segment_uuid
from app.meetings.repository import MeetingRepository, get_meetings
from app.protocols.errors import ProtocolExportError
from app.protocols.loader import ProtocolLoader
from app.speech.repository import TranscriptRecord
from app.tasks.models import Task
from app.tasks.repository import TaskRepository
from app.tasks.schemas import TaskCreate

from .test_api_loader import database as shared_database


@pytest.fixture
def database(tmp_path, protocol):
    yield from shared_database.__wrapped__(tmp_path, protocol)


def canonical(engine, original):
    result = CanonicalTranscript(
        source_audio_id=original.source_audio_id,
        canonical_language="ru",
        segments=[
            dict(
                id=x.id,
                start=x.start,
                end=x.end,
                speaker_id=x.speaker_id,
                original_text=x.text,
                canonical_text=x.text,
            )
            for x in original.segments
        ],
    )
    with Session(engine) as s, s.begin():
        s.add(
            CanonicalTranscriptRecord(
                source_audio_id=original.source_audio_id,
                source_hash=hashlib.sha256(original.model_dump_json().encode()).hexdigest(),
                profile_hash="d" * 64,
                payload=result.model_dump(mode="json"),
            )
        )
    return result


def publish(engine, protocol, original):
    ref = segment_uuid(original.segments[0].id)
    AnalysisRepository(engine).publish(
        protocol.meeting_id,
        AnalysisInput(
            transcript_id=protocol.source_transcript_id,
            summary="Summary",
            decisions=[DecisionInput(text="Decision", source_segment_ids=[ref])],
            tasks=[TaskCreate(text="Generated", source_segment_ids=[ref])],
        ),
    )


def test_export_uses_frontend_uuids_and_rejects_dangling_evidence(database, protocol):
    engine, original = database
    publish(engine, protocol, original)
    result = ProtocolLoader(engine).load(protocol.meeting_id)
    ref = str(segment_uuid(original.segments[0].id))
    assert result.transcript[0].id == ref
    assert result.decisions[0].source_segment_ids == (ref,)
    assert result.action_items[0].source_segment_ids == (ref,)
    with Session(engine) as s, s.begin():
        decision = s.scalar(select(Decision))
        decision.source_segment_ids = [str(uuid4())]
    with pytest.raises(ProtocolExportError):
        ProtocolLoader(engine).load(protocol.meeting_id)
    with Session(engine) as s:
        assert s.get(
            TranscriptRecord, protocol.source_transcript_id
        ).payload == original.model_dump(mode="json")


def test_reprocessing_keeps_manual_and_only_current_generated_everywhere(database, protocol):
    engine, original = database
    tasks = TaskRepository(engine)
    manual = tasks.create(
        protocol.meeting_id,
        TaskCreate(
            text="Manual",
            source_segment_ids=[segment_uuid(original.segments[0].id)],
        ),
    )
    publish(engine, protocol, original)
    with Session(engine) as s, s.begin():
        newer = TranscriptRecord(
            source_audio_id=original.source_audio_id,
            profile_hash="e" * 64,
            payload=original.model_dump(mode="json"),
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        s.add(newer)
        s.flush()
        new_id = newer.id
    AnalysisRepository(engine).publish(
        protocol.meeting_id,
        AnalysisInput(
            transcript_id=new_id,
            summary="New",
            tasks=[
                TaskCreate(
                    text="Current", source_segment_ids=[segment_uuid(original.segments[0].id)]
                )
            ],
        ),
    )
    result = MeetingRepository(engine).result(protocol.meeting_id)
    exported = ProtocolLoader(engine).load(protocol.meeting_id)
    for items in (
        result["tasks"],
        tasks.list(meeting_id=protocol.meeting_id)["items"],
        tasks.list()["items"],
    ):
        assert {x.text for x in items} == {"Manual", "Current"}
        assert next(x for x in items if x.id == manual.id).source_segment_ids == []
    assert {x.text for x in exported.action_items} == {"Manual", "Current"}
    assert next(x for x in exported.action_items if x.text == "Manual").source_segment_ids == ()
    with Session(engine) as s:
        assert len(list(s.scalars(select(Task)))) == 3  # history is retained
        assert s.get(Task, manual.id).source_segment_ids  # source history not erased


class Runner:
    def __init__(self):
        self.calls = []
        self.context = None

    def workflow(self, _):
        return nullcontext()

    async def close(self):
        pass

    async def run(self, stage, payload):
        self.calls.append(stage)
        if stage == "extraction":
            self.source = payload.targets[0].id
            return ChunkAnalysis(
                action_items=[],
                decisions=[],
                unresolved_references=[],
                important_facts=[GroundedText(text="Факт", source_segment_ids=[self.source])],
            )
        if stage == "resolver":
            return ResolvedMeetingFacts(
                action_items=[
                    ResolvedActionCandidate(
                        task="Проверить",
                        assignee_participant_id=None,
                        assignee_name=None,
                        deadline=None,
                        deadline_text=None,
                        deadline_kind="unspecified",
                        needs_review=True,
                        source_segment_ids=[self.source],
                    )
                ],
                decisions=[],
                unresolved_items=[],
            )
        if stage == "summary":
            return MeetingSummary(
                claims=[GroundedText(text="Факт", source_segment_ids=[self.source])],
                topics=[],
                key_points=[],
                unresolved_questions=[],
            )
        assert stage == "review"
        return ReviewResult(approved=True, issues=[])


def coordinator(engine, runner):
    settings = Settings(_env_file=None, meeting_tracing_enabled=False)
    pipeline = MeetingIntelligenceService(
        runner,
        settings,
        MeetingAnalysisRepository(engine),
        intelligence_profile(settings),
        SpeakerResolutionService(
            runner, settings, SpeakerMappingRepository(engine), speaker_resolution_profile(settings)
        ),
    )
    return AnalysisCoordinator(pipeline, engine)


def test_analyze_http_runs_pipeline_publishes_result_and_is_idempotent(database, protocol):
    engine, original = database
    canonical(engine, original)
    runner = Runner()
    service = coordinator(engine, runner)
    repo = MeetingRepository(engine)
    app.dependency_overrides[get_analysis_coordinator] = lambda: service
    app.dependency_overrides[get_meetings] = lambda: repo
    try:
        with TestClient(app) as client:
            url = f"/api/v1/meetings/{protocol.meeting_id}"
            response = client.post(url + "/analyze")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data == client.get(url + "/result").json()
            assert data["summary"] == "Факт"
            assert data["tasks"][0]["source_segment_ids"] == [
                str(segment_uuid(original.segments[0].id))
            ]
            assert data["tasks"][0]["id"] == data["analysis_details"]["action_items"][0]["id"]
            assert data["meeting"]["processing_status"] == "ready"
            assert client.post(url + "/analyze").json() == data
            assert runner.calls == ["extraction", "resolver", "summary", "review"]
            assert ProtocolLoader(engine).load(protocol.meeting_id).summary == "Факт"
    finally:
        app.dependency_overrides.pop(get_analysis_coordinator)
        app.dependency_overrides.pop(get_meetings)


def test_missing_canonical_does_not_call_agent(database, protocol):
    engine, _ = database
    runner = Runner()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(coordinator(engine, runner).analyze(protocol.meeting_id))
    assert exc.value.status_code == 409
    assert runner.calls == []


def test_agent_failure_does_not_publish_partial_result(database, protocol):
    engine, original = database
    canonical(engine, original)

    class Broken(Runner):
        async def run(self, stage, payload):
            raise ExtractionAgentError

    with pytest.raises(ExtractionAgentError):
        asyncio.run(coordinator(engine, Broken()).analyze(protocol.meeting_id))
    with Session(engine) as s:
        assert s.get(MeetingAnalysis, protocol.source_transcript_id) is None
        assert list(s.scalars(select(Task))) == []


def test_new_transcript_during_llm_call_prevents_publication(database, protocol):
    engine, original = database
    canonical(engine, original)

    class Changed(Runner):
        async def run(self, stage, payload):
            if stage == "review":
                with Session(engine) as s, s.begin():
                    s.add(
                        TranscriptRecord(
                            source_audio_id=original.source_audio_id,
                            profile_hash="f" * 64,
                            payload=original.model_dump(mode="json"),
                            created_at=datetime.now(UTC) + timedelta(seconds=1),
                        )
                    )
            return await super().run(stage, payload)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(coordinator(engine, Changed()).analyze(protocol.meeting_id))
    assert exc.value.status_code == 409
    with Session(engine) as s:
        assert s.get(MeetingAnalysis, protocol.source_transcript_id) is None


def test_migration_backfills_manual_origin_from_audit(database, protocol):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    engine, original = database
    manual = TaskRepository(engine).create(protocol.meeting_id, TaskCreate(text="Manual"))
    publish(engine, protocol, original)
    migration_path = Path(__file__).parents[2] / "migrations/versions/0008_agent_integration.py"
    spec = importlib.util.spec_from_file_location("agent_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        # Reconstruct the pre-0008 shape with actual historical rows and audit entries.
        for table in ("agent_analysis_artifacts", "speaker_mappings"):
            connection.exec_driver_sql(f"DROP TABLE {table}")
        connection.exec_driver_sql("ALTER TABLE meeting_tasks DROP COLUMN origin")
        connection.exec_driver_sql("ALTER TABLE meeting_analyses DROP COLUMN details")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        rows = dict(connection.execute(text("SELECT text, origin FROM meeting_tasks")).all())
        assert rows == {"Manual": "manual", "Generated": "generated"}
    result = TaskRepository(engine).list(meeting_id=protocol.meeting_id)
    assert any(item.id == manual.id for item in result["items"])
