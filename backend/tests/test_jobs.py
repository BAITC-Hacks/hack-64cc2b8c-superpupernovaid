import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.application.jobs import ProcessJob, QueueUnavailable, SubmitJob
from app.bootstrap import get_repository, get_submit_job
from app.config import Settings
from app.domain.jobs import JobStatus
from app.entrypoints.api import app
from app.infrastructure.agents import DemoOrchestrator, OpenAIOrchestrator
from app.infrastructure.database import Base, SqlJobRepository


class RecordingQueue:
    def __init__(self):
        self.ids = []

    def enqueue(self, job_id):
        self.ids.append(job_id)


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield SqlJobRepository(engine)
    engine.dispose()


def test_api_to_processing(repository):
    queue = RecordingQueue()
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_submit_job] = lambda: SubmitJob(repository, queue)
    try:
        with TestClient(app) as client:
            assert client.get("/docs").status_code == 200
            assert "/api/v1/jobs" in client.get("/openapi.json").json()["paths"]
            assert client.post("/api/v1/jobs", json={"prompt": "   "}).status_code == 422
            assert client.post("/api/v1/jobs", json={"prompt": "x" * 10001}).status_code == 422
            response = client.post("/api/v1/jobs", json={"prompt": "Привет"})
            assert response.status_code == 202
            assert response.json()["status"] == "queued"
            asyncio.run(ProcessJob(repository, DemoOrchestrator()).execute(queue.ids[0]))
            result = client.get(f"/api/v1/jobs/{queue.ids[0]}").json()
            assert result["status"] == "succeeded"
            assert "Деморежим" in result["result"]
            assert client.get(f"/api/v1/jobs/{uuid4()}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_failed_agent_and_duplicate_delivery(repository):
    class BrokenAgent:
        calls = 0

        async def run(self, prompt):
            self.calls += 1
            raise RuntimeError("sensitive provider error")

    agent = BrokenAgent()
    job = SubmitJob(repository, RecordingQueue()).execute("Test")
    processor = ProcessJob(repository, agent)
    asyncio.run(processor.execute(job.id))
    asyncio.run(processor.execute(job.id))
    assert agent.calls == 1
    assert repository.get(job.id).status == JobStatus.FAILED
    assert "sensitive" not in repository.get(job.id).error


def test_broker_failure(repository):
    class BrokenQueue(RecordingQueue):
        def enqueue(self, job_id):
            self.ids.append(job_id)
            raise ConnectionError()

    queue = BrokenQueue()
    with pytest.raises(QueueUnavailable):
        SubmitJob(repository, queue).execute("Test")
    assert repository.get(queue.ids[0]).status == JobStatus.FAILED


def test_openai_adapter_wiring(monkeypatch):
    from agents import Runner

    async def fake_run(agent, prompt, **kwargs):
        assert len(agent.handoffs) == 1
        assert kwargs["max_turns"] == 8
        assert kwargs["run_config"].tracing_disabled
        return SimpleNamespace(final_output="adapter result")

    monkeypatch.setattr(Runner, "run", fake_run)
    settings = Settings(_env_file=None, ai_mode="openai", openai_api_key="test-only")
    assert asyncio.run(OpenAIOrchestrator(settings).run("hello")) == "adapter result"


def test_openai_requires_key():
    with pytest.raises(ValueError):
        Settings(_env_file=None, ai_mode="openai", openai_api_key="")


def test_worker_entrypoint(repository, monkeypatch):
    from app.entrypoints import worker

    job = SubmitJob(repository, RecordingQueue()).execute("Through Celery")
    monkeypatch.setattr(
        worker, "get_process_job", lambda: ProcessJob(repository, DemoOrchestrator())
    )
    result = worker.process_job.apply(args=[str(job.id)], throw=True)
    assert result.successful()
    assert repository.get(job.id).status == JobStatus.SUCCEEDED
