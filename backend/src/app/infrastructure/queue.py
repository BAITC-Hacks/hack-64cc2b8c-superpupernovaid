from uuid import UUID

from celery import Celery

from app.config import get_settings

celery_app = Celery(
    "superpupernova", broker=get_settings().redis_url, include=["app.entrypoints.worker"]
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_default_queue="jobs",
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
    task_publish_retry=False,
)


class CeleryTaskQueue:
    def enqueue(self, job_id: UUID) -> None:
        celery_app.send_task("jobs.process", args=[str(job_id)], task_id=str(job_id))
