from app.infrastructure.queue import celery_app


class MeetingProcessingQueue:
    def enqueue(self, run_id):
        celery_app.send_task("meetings.process", args=[str(run_id)], task_id=str(run_id))
