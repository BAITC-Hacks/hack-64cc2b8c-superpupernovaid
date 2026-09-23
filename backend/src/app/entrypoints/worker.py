import asyncio
from uuid import UUID

from celery.signals import task_failure, worker_process_shutdown

from app.bootstrap import get_process_job
from app.infrastructure.queue import celery_app


@celery_app.task(name="jobs.process")
def process_job(job_id: str) -> None:
    asyncio.run(get_process_job().execute(UUID(job_id)))


# One event loop per prefork child: cached async clients cannot migrate between loops.
_meeting_runner = None


@celery_app.task(name="meetings.process", acks_late=True, time_limit=3600)
def process_meeting(run_id: str) -> None:
    global _meeting_runner
    from app.processing.dependencies import get_meeting_processing_service

    if _meeting_runner is None:
        _meeting_runner = asyncio.Runner()
    _meeting_runner.run(get_meeting_processing_service().execute(UUID(run_id)))


@task_failure.connect
def meeting_worker_failure(sender=None, task_id=None, **kwargs):
    if getattr(sender, "name", None) == "meetings.process" and task_id:
        from app.processing.dependencies import get_processing_repository

        get_processing_repository().fail(
            UUID(task_id), "processing_worker_failed", "Worker stopped; retry processing"
        )


@worker_process_shutdown.connect
def close_meeting_worker(**kwargs):
    global _meeting_runner
    if _meeting_runner is None:
        return
    from app.canonicalization.dependencies import shutdown_canonicalization
    from app.intelligence.dependencies import shutdown_analysis
    from app.protocols.dependencies import shutdown_exports
    from app.speech.dependencies import shutdown_speech

    async def close():
        try:
            await shutdown_analysis()
        finally:
            try:
                await shutdown_canonicalization()
            finally:
                try:
                    await shutdown_speech()
                finally:
                    await shutdown_exports()

    try:
        _meeting_runner.run(close())
    finally:
        _meeting_runner.close()
        _meeting_runner = None


@celery_app.task(name="notifications.scan")
def scan_task_reminders():
    from app.notifications.service import get_reminders

    return get_reminders().scan()
