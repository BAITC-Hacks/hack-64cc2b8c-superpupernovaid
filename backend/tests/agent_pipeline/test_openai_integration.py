"""Explicit opt-in; sends only synthetic meeting text, never real recordings."""

import asyncio
import os

import pytest

from app.config import Settings
from app.intelligence.pipeline.dependencies import (
    intelligence_profile,
    speaker_resolution_profile,
    validate_intelligence_configuration,
)
from app.intelligence.pipeline.repository import MeetingAnalysisRepository
from app.intelligence.pipeline.runner import OpenAIMeetingAgents
from app.intelligence.pipeline.service import MeetingIntelligenceService
from app.intelligence.pipeline.speaker_repository import SpeakerMappingRepository
from app.intelligence.pipeline.speaker_resolution import SpeakerResolutionService


@pytest.mark.integration
@pytest.mark.openai
@pytest.mark.agents
@pytest.mark.skipif(
    os.getenv("RUN_MEETING_AGENTS_INTEGRATION") != "1", reason="Explicit API opt-in"
)
def test_real_synthetic_meeting(meeting_input, engine):
    settings = Settings(meeting_intelligence_enabled=True, meeting_tracing_enabled=False)
    validate_intelligence_configuration(settings)
    runner = OpenAIMeetingAgents(settings)
    service = MeetingIntelligenceService(
        runner,
        settings,
        MeetingAnalysisRepository(engine),
        intelligence_profile(settings),
        SpeakerResolutionService(
            runner, settings, SpeakerMappingRepository(engine), speaker_resolution_profile(settings)
        ),
    )

    async def scenario():
        try:
            return await service.analyze(meeting_input)
        finally:
            await service.close()

    result = asyncio.run(scenario())
    assert result.action_items
    assert any(set(a.source_segment_ids) == {"seg_041", "seg_057"} for a in result.action_items)
    assert all(a.source_segment_ids for a in result.action_items)
