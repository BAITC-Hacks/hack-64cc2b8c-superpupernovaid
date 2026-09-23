import asyncio
from contextlib import nullcontext
from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.audio import models as audio_models  # noqa: F401
from app.canonicalization.models import CanonicalTranscript, CanonicalTranscriptSegment
from app.config import Settings
from app.infrastructure.database import Base
from app.intelligence.pipeline.dependencies import intelligence_profile, speaker_resolution_profile
from app.intelligence.pipeline.models import (
    CandidateActionItem,
    ChunkAnalysis,
    GroundedText,
    MeetingContext,
    MeetingIntelligenceInput,
    MeetingSummary,
    Participant,
    ResolvedActionCandidate,
    ResolvedMeetingFacts,
    ReviewResult,
    SpeakerMapping,
    SpeakerResolutionResult,
)
from app.intelligence.pipeline.repository import MeetingAnalysisRepository
from app.intelligence.pipeline.service import MeetingIntelligenceService
from app.intelligence.pipeline.speaker_repository import SpeakerMappingRepository
from app.intelligence.pipeline.speaker_resolution import SpeakerResolutionService
from app.media import models as media_models  # noqa: F401


def grounded(text="Интеграция", ids=None):
    return GroundedText(text=text, source_segment_ids=ids or ["seg_041", "seg_057"])


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.active = self.peak = 0
        self.review = ReviewResult(approved=True, issues=[])
        self.resolved = ResolvedMeetingFacts(
            action_items=[
                ResolvedActionCandidate(
                    task="Завершить интеграцию",
                    assignee_participant_id="daniyar",
                    assignee_name="Данияр",
                    deadline=date(2026, 9, 25),
                    deadline_text="до пятницы",
                    deadline_kind="relative",
                    source_segment_ids=["seg_041", "seg_057"],
                    needs_review=False,
                )
            ],
            decisions=[],
            unresolved_items=[],
        )

    def workflow(self, meeting_id):
        return nullcontext()

    async def close(self):
        pass

    async def run(self, stage, payload):
        self.calls.append((stage, payload))
        if stage == "speaker_resolution":
            return SpeakerResolutionResult(mappings=[SpeakerMapping(speaker_id=payload.speaker_id)])
        if stage == "extraction":
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01)
                actions, refs = [], []
                for segment in payload.targets:
                    if segment.id == "seg_041":
                        actions.append(
                            CandidateActionItem(
                                task="Интеграция",
                                assignee_text="Данияр",
                                source_segment_ids=[segment.id],
                            )
                        )
                    elif segment.id == "seg_057":
                        refs.append(grounded("Это нужно закончить до пятницы", [segment.id]))
                return ChunkAnalysis(
                    action_items=actions,
                    decisions=[],
                    important_facts=[],
                    unresolved_references=refs,
                )
            finally:
                self.active -= 1
        if stage == "resolver":
            return self.resolved.model_copy(deep=True)
        if stage == "summary":
            return MeetingSummary(
                claims=[grounded("Обсудили интеграцию.")],
                topics=[grounded()],
                key_points=[],
                unresolved_questions=[],
            )
        return self.review


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        meeting_chunk_max_segments=1,
        meeting_chunk_overlap_segments=1,
        agent_max_concurrency=2,
        meeting_tracing_enabled=False,
    )


@pytest.fixture
def meeting_input():
    texts = [
        ("seg_041", "Данияр, возьмите интеграцию."),
        ("seg_057", "И это нужно закончить до пятницы."),
        ("seg_060", "Спасибо, на этом всё."),
    ]
    return MeetingIntelligenceInput(
        meeting=MeetingContext(
            meeting_id=uuid4(),
            started_at=datetime.fromisoformat("2026-09-23T10:00:00+05:00"),
            timezone="Asia/Almaty",
        ),
        participants=[Participant(id="daniyar", name="Данияр")],
        transcript=CanonicalTranscript(
            source_audio_id=uuid4(),
            canonical_language="ru",
            segments=[
                CanonicalTranscriptSegment(
                    id=id,
                    start=i * 5,
                    end=i * 5 + 4,
                    speaker_id="SPEAKER_00",
                    original_text=text,
                    canonical_text=text,
                )
                for i, (id, text) in enumerate(texts)
            ],
        ),
    )


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def fake():
    return FakeRunner()


@pytest.fixture
def service(settings, engine, fake):
    return MeetingIntelligenceService(
        fake,
        settings,
        MeetingAnalysisRepository(engine),
        intelligence_profile(settings),
        SpeakerResolutionService(
            fake, settings, SpeakerMappingRepository(engine), speaker_resolution_profile(settings)
        ),
    )
