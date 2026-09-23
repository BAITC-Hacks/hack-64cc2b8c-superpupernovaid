from functools import lru_cache

from app.application.jobs import ProcessJob, SubmitJob
from app.application.ports import FileStorage
from app.audio.ffmpeg import FfmpegAudioConverter
from app.audio.repository import AudioRepository
from app.audio.service import AudioPreprocessor
from app.config import get_settings
from app.infrastructure.agents import DemoOrchestrator, OpenAIOrchestrator
from app.infrastructure.database import SqlJobRepository
from app.media.probe import FFprobeMediaProbe
from app.media.repository import MediaRepository
from app.media.service import MediaService
from app.media.storage import LocalMediaStorage


def get_repository() -> SqlJobRepository:
    return SqlJobRepository()


def get_submit_job() -> SubmitJob:
    from app.infrastructure.queue import CeleryTaskQueue

    return SubmitJob(get_repository(), CeleryTaskQueue())


def get_process_job() -> ProcessJob:
    settings = get_settings()
    orchestrator = (
        DemoOrchestrator() if settings.ai_mode == "mock" else OpenAIOrchestrator(settings)
    )
    return ProcessJob(get_repository(), orchestrator)


@lru_cache
def get_media_storage() -> FileStorage:
    return LocalMediaStorage(get_settings().media_upload_dir)


@lru_cache
def get_media_service() -> MediaService:
    settings = get_settings()
    return MediaService(
        storage=get_media_storage(),
        probe=FFprobeMediaProbe(
            settings.media_ffprobe_timeout_seconds, settings.media_ffprobe_executable
        ),
        repository=get_media_repository(),
        max_bytes=settings.media_max_file_size_bytes,
        allowed_formats=frozenset(settings.media_allowed_formats),
    )


@lru_cache
def get_media_repository() -> MediaRepository:
    return MediaRepository()


@lru_cache
def get_audio_preprocessor() -> AudioPreprocessor:
    settings = get_settings()
    from app.meetings.progress import ProcessingTracker

    return AudioPreprocessor(
        storage=get_media_storage(),
        converter=FfmpegAudioConverter(
            FFprobeMediaProbe(
                settings.media_ffprobe_timeout_seconds, settings.media_ffprobe_executable
            ),
            settings.audio_ffmpeg_timeout_seconds,
            settings.audio_ffmpeg_executable,
        ),
        repository=AudioRepository(),
        config=settings.audio_processing_config,
        max_concurrency=settings.audio_max_concurrent_processes,
        tracker=ProcessingTracker(),
    )
