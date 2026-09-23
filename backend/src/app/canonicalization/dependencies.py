import hashlib
import json
from functools import lru_cache

from app.canonicalization.agent import INSTRUCTIONS, PROMPT_VERSION, OpenAITranscriptCanonicalizer
from app.canonicalization.errors import CanonicalizationConfigurationError
from app.canonicalization.repository import CanonicalizationRepository
from app.canonicalization.service import TranscriptCanonicalizationService
from app.config import get_settings
from app.speech.repository import SpeechRepository


def validate_canonicalization_configuration(settings):
    if settings.transcript_canonicalization_enabled and (
        not settings.transcript_canonicalization_model.strip()
        or not settings.openai_api_key.get_secret_value().strip()
    ):
        raise CanonicalizationConfigurationError


def canonicalization_profile(settings):
    profile = {
        "pipeline": PROMPT_VERSION,
        "instructions": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
        "model": settings.transcript_canonicalization_model,
        "language": settings.transcript_canonical_language,
        "batch_segments": settings.canonicalization_batch_max_segments,
        "batch_bytes": settings.canonicalization_batch_max_bytes,
        "context": settings.canonicalization_context_segments,
        "output_tokens": settings.canonicalization_max_output_tokens,
    }
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


@lru_cache
def get_canonicalization_service() -> TranscriptCanonicalizationService | None:
    settings = get_settings()
    if not settings.transcript_canonicalization_enabled:
        return None
    validate_canonicalization_configuration(settings)
    return TranscriptCanonicalizationService(
        OpenAITranscriptCanonicalizer(settings),
        settings,
        CanonicalizationRepository(),
        canonicalization_profile(settings),
    )


@lru_cache
def get_canonicalization_speech_repository():
    return SpeechRepository()


async def shutdown_canonicalization():
    service = get_canonicalization_service()
    if service is not None:
        await service.close()
    get_canonicalization_service.cache_clear()
    get_canonicalization_speech_repository.cache_clear()
