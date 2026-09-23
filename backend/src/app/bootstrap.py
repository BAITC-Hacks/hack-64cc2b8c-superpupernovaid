from app.application.jobs import ProcessJob, SubmitJob
from app.config import get_settings
from app.infrastructure.agents import DemoOrchestrator, OpenAIOrchestrator
from app.infrastructure.database import SqlJobRepository


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
