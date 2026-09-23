from functools import lru_cache

from app.application.jobs import ProcessJob, SubmitJob
from app.application.ports import FileStorage
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
        repository=MediaRepository(),
        max_bytes=settings.media_max_file_size_bytes,
        allowed_formats=frozenset(settings.media_allowed_formats),
    )
