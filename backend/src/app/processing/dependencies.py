import asyncio
from functools import lru_cache

from app.bootstrap import get_audio_preprocessor, get_media_repository
from app.canonicalization.dependencies import get_canonicalization_service
from app.config import get_settings
from app.processing.errors import (
    ProcessingConfigurationError,
    ProcessingLanguageError,
    ProcessingNotFound,
)
from app.processing.repository import ProcessingRepository
from app.processing.service import MeetingProcessingService, SubmitMeetingProcessing
from app.protocols.dependencies import get_export_service, get_protocol_loader
from app.speech.dependencies import get_speech_service


def analysis_coordinator():
    # This integration seam is supplied by the parallel Meeting Intelligence module.
    from app.intelligence.dependencies import get_analysis_coordinator

    return get_analysis_coordinator()


def preflight(meeting_id, media_id):
    language = get_processing_repository().language(meeting_id, media_id)
    settings = get_settings()
    if settings.asr_provider == "nvidia" and language != "ru":
        raise ProcessingLanguageError
    if not settings.speech_enabled or not settings.transcript_canonicalization_enabled:
        raise ProcessingConfigurationError
    from app.intelligence.pipeline.dependencies import validate_intelligence_configuration

    if not settings.meeting_intelligence_enabled:
        raise ProcessingConfigurationError
    validate_intelligence_configuration(settings)


class ExistingMeetingStages:
    async def validate(self, run):
        await asyncio.to_thread(preflight, run.meeting_id, run.media_id)

    async def preprocess(self, run):
        media = await asyncio.to_thread(get_media_repository().get, run.meeting_id, run.media_id)
        if media is None:
            raise ProcessingNotFound
        return await get_audio_preprocessor().process(media)

    async def speech(self, run, audio):
        service = get_speech_service()
        if service is None:
            raise ProcessingConfigurationError
        return await service.process(audio)

    async def canonicalize(self, run, transcript):
        service = get_canonicalization_service()
        if service is None:
            raise ProcessingConfigurationError
        return await service.canonicalize(transcript)

    async def speakers(self, run):
        coordinator = analysis_coordinator()
        if coordinator is None:
            raise ProcessingConfigurationError
        _, context = await asyncio.to_thread(coordinator.load, run.meeting_id)
        if context is not None:
            # The analyzer reuses this exact persisted mapping artifact.
            await coordinator.pipeline.speaker_resolution.resolve(context)

    async def analyze(self, run):
        coordinator = analysis_coordinator()
        if coordinator is None:
            raise ProcessingConfigurationError
        await coordinator.analyze(run.meeting_id)

    async def export(self, run):
        protocol = await asyncio.to_thread(get_protocol_loader().load, run.meeting_id)
        result = []
        for format in run.export_formats:
            document = await get_export_service().export(protocol, format)
            result.append(document.model_dump(mode="json"))
        return result


@lru_cache
def get_processing_repository():
    return ProcessingRepository()


def get_submit_meeting_processing():
    from app.processing.queue import MeetingProcessingQueue

    return SubmitMeetingProcessing(get_processing_repository(), MeetingProcessingQueue(), preflight)


def get_meeting_processing_service():
    return MeetingProcessingService(get_processing_repository(), ExistingMeetingStages())
