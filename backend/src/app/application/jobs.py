import logging
from uuid import UUID

from app.application.ports import AgentOrchestrator, JobRepository, TaskQueue
from app.domain.jobs import Job, JobStatus

logger = logging.getLogger(__name__)


class QueueUnavailable(Exception):
    pass


class SubmitJob:
    def __init__(self, repository: JobRepository, queue: TaskQueue):
        self.repository, self.queue = repository, queue

    def execute(self, prompt: str) -> Job:
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 10000:
            raise ValueError("Prompt must contain 1–10000 characters")
        job = Job(prompt=prompt)
        self.repository.add(job)
        try:
            self.queue.enqueue(job.id)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = "Не удалось передать задание в очередь."
            self.repository.save(job)
            logger.warning("Queue publish failed for %s (%s)", job.id, type(exc).__name__)
            raise QueueUnavailable from exc
        return job


class ProcessJob:
    def __init__(self, repository: JobRepository, orchestrator: AgentOrchestrator):
        self.repository, self.orchestrator = repository, orchestrator

    async def execute(self, job_id: UUID) -> None:
        # Atomic claim prevents concurrent duplicate deliveries from running the same job.
        if not self.repository.claim(job_id):
            return
        job = self.repository.get(job_id)
        if job is None:
            return
        try:
            job.result = await self.orchestrator.run(job.prompt)
            job.status = JobStatus.SUCCEEDED
        except Exception as exc:
            logger.warning("Agent failed for %s (%s)", job.id, type(exc).__name__)
            job.status = JobStatus.FAILED
            job.error = "Обработка завершилась ошибкой. Проверьте настройки ИИ и логи воркера."
        self.repository.save(job)
