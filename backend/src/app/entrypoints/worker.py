import asyncio
from uuid import UUID

from app.bootstrap import get_process_job
from app.infrastructure.queue import celery_app


@celery_app.task(name="jobs.process")
def process_job(job_id: str) -> None:
    asyncio.run(get_process_job().execute(UUID(job_id)))
