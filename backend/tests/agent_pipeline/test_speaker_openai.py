"""Opt-in semantic checks using synthetic conversations; no real meeting text."""

import asyncio
import os
from uuid import uuid4

import pytest

from app.canonicalization.models import CanonicalTranscript, CanonicalTranscriptSegment
from app.config import Settings
from app.intelligence.pipeline.dependencies import (
    speaker_resolution_profile,
    validate_intelligence_configuration,
)
from app.intelligence.pipeline.models import MeetingContext, MeetingIntelligenceInput, Participant
from app.intelligence.pipeline.runner import OpenAIMeetingAgents
from app.intelligence.pipeline.speaker_repository import SpeakerMappingRepository
from app.intelligence.pipeline.speaker_resolution import SpeakerResolutionService

CASES = [
    (
        [
            ("SPEAKER_00", "Жандос Талгатович, по инвестициям что у нас?"),
            ("SPEAKER_02", "Да, докладываю. По инвестпрограмме за сентябрь освоение 68%."),
        ],
        "SPEAKER_02",
        "resolved",
        "p3",
    ),
    ([("SPEAKER_01", "У нас есть юрист Ерлан.")], "SPEAKER_01", "unresolved", None),
    (
        [
            ("SPEAKER_02", "Меня зовут Жандос Талгатович, докладываю об инвестициях."),
            ("SPEAKER_00", "Теперь следующий докладчик."),
            ("SPEAKER_02", "Меня зовут Салтанат. Я другой участник, докладываю по кадрам."),
        ],
        "SPEAKER_02",
        "conflict",
        None,
    ),
]


@pytest.mark.integration
@pytest.mark.openai
@pytest.mark.agents
@pytest.mark.skipif(
    os.getenv("RUN_SPEAKER_RESOLUTION_INTEGRATION") != "1",
    reason="Explicit synthetic OpenAI opt-in",
)
@pytest.mark.parametrize("turns,speaker,status,participant", CASES)
def test_real_speaker_semantics(engine, turns, speaker, status, participant):
    settings = Settings(meeting_intelligence_enabled=True, meeting_tracing_enabled=False)
    validate_intelligence_configuration(settings)
    runner = OpenAIMeetingAgents(settings)
    service = SpeakerResolutionService(
        runner, settings, SpeakerMappingRepository(engine), speaker_resolution_profile(settings)
    )
    data = MeetingIntelligenceInput(
        meeting=MeetingContext(meeting_id=uuid4()),
        participants=[
            Participant(id="p3", name="Жандос Талгатович", role="инвестиции"),
            Participant(id="p5", name="Салтанат", role="кадры"),
            Participant(id="p6", name="Ерлан", role="юрист"),
        ],
        transcript=CanonicalTranscript(
            source_audio_id=uuid4(),
            canonical_language="ru",
            segments=[
                CanonicalTranscriptSegment(
                    id=f"s{i}",
                    start=i * 5,
                    end=i * 5 + 4,
                    speaker_id=label,
                    original_text=text,
                    canonical_text=text,
                )
                for i, (label, text) in enumerate(turns)
            ],
        ),
    )

    async def scenario():
        try:
            return await service.resolve(data)
        finally:
            await runner.close()

    result = asyncio.run(scenario())
    mapping = next(m for m in result.mappings if m.speaker_id == speaker)
    assert mapping.status == status and mapping.participant_id == participant
    if status == "conflict":
        assert set(mapping.candidate_participant_ids) == {"p3", "p5"}
