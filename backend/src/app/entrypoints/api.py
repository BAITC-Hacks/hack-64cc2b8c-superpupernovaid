import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis import Redis
from sqlalchemy import text

from app.application.jobs import QueueUnavailable, SubmitJob
from app.application.ports import JobRepository
from app.audio.router import router as audio_router
from app.bootstrap import get_repository, get_submit_job
from app.config import get_settings
from app.domain.jobs import JobStatus
from app.infrastructure.database import get_engine
from app.media.router import router as media_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="SuperPuperNova API",
    version="0.1.0",
    description="Modular monolith · media ingestion and asynchronous jobs",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class JobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)

    @field_validator("prompt")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt cannot be blank")
        return value.strip()


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    prompt: str
    status: JobStatus
    result: str | None
    error: str | None
    created_at: datetime


@app.get("/api/v1/health", tags=["Health"])
def health():
    return {"status": "ok", "ai_mode": get_settings().ai_mode}


@app.get("/api/v1/ready", tags=["Health"])
def readiness():
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        with Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        ) as redis:
            redis.ping()
    except Exception:
        raise HTTPException(503, "Database or queue unavailable") from None
    return {"status": "ready"}


@app.post("/api/v1/jobs", status_code=202, response_model=JobResponse, tags=["Jobs"])
def submit_job(payload: JobRequest, use_case: Annotated[SubmitJob, Depends(get_submit_job)]):
    try:
        return use_case.execute(payload.prompt)
    except QueueUnavailable:
        raise HTTPException(503, "Queue unavailable; please retry later") from None


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, tags=["Jobs"])
def read_job(job_id: UUID, repository: Annotated[JobRepository, Depends(get_repository)]):
    job = repository.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


app.include_router(media_router)

app.include_router(audio_router)
