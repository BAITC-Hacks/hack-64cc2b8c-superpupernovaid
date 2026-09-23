import hashlib
import json
from functools import lru_cache

from app.config import get_settings
from app.intelligence.pipeline.agents import COMMON, SPECS
from app.intelligence.pipeline.errors import (
    AgentConfigurationError,
    SpeakerResolutionConfigurationError,
)
from app.intelligence.pipeline.repository import MeetingAnalysisRepository
from app.intelligence.pipeline.runner import OpenAIMeetingAgents
from app.intelligence.pipeline.service import MeetingIntelligenceService
from app.intelligence.pipeline.speaker_repository import SpeakerMappingRepository
from app.intelligence.pipeline.speaker_resolution import SpeakerResolutionService


def validate_intelligence_configuration(settings):
    if (
        settings.meeting_intelligence_enabled
        and not settings.meeting_speaker_resolution_model.strip()
    ):
        raise SpeakerResolutionConfigurationError
    if settings.meeting_intelligence_enabled and (
        not settings.openai_api_key.get_secret_value().strip()
        or any(not getattr(settings, f"meeting_{stage}_model").strip() for stage in SPECS)
    ):
        raise AgentConfigurationError


def intelligence_profile(settings):
    profile = {
        "pipeline": "intelligence-v2-speaker-resolution",
        "common": COMMON,
        "prompts": {s: [m.VERSION, m.INSTRUCTIONS] for s, (m, _) in SPECS.items()},
        "models": {s: getattr(settings, f"meeting_{s}_model") for s in SPECS},
        "chunk": [
            settings.meeting_chunk_max_segments,
            settings.meeting_chunk_max_bytes,
            settings.meeting_chunk_overlap_segments,
        ],
        "speaker_context_segments": settings.speaker_resolution_max_context_segments,
        "input_bytes": settings.meeting_agent_max_input_bytes,
        "output_tokens": settings.meeting_max_output_tokens,
    }
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


@lru_cache
def get_intelligence_service():
    settings = get_settings()
    if not settings.meeting_intelligence_enabled:
        return None
    validate_intelligence_configuration(settings)
    runner = OpenAIMeetingAgents(settings)
    return MeetingIntelligenceService(
        runner,
        settings,
        MeetingAnalysisRepository(),
        intelligence_profile(settings),
        SpeakerResolutionService(
            runner, settings, SpeakerMappingRepository(), speaker_resolution_profile(settings)
        ),
    )


async def shutdown_intelligence():
    service = get_intelligence_service()
    if service is not None:
        await service.close()
    get_intelligence_service.cache_clear()


def speaker_resolution_profile(settings):
    module, _ = SPECS["speaker_resolution"]
    profile = {
        "pipeline": "speaker-context-v1",
        "prompt": [COMMON, module.VERSION, module.INSTRUCTIONS],
        "model": settings.meeting_speaker_resolution_model,
        "segments": settings.speaker_resolution_max_context_segments,
        "bytes": settings.meeting_agent_max_input_bytes,
        "output_tokens": settings.meeting_max_output_tokens,
    }
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
