from datetime import datetime
from functools import lru_cache
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Uuid, create_engine, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings
from app.domain.jobs import Job, JobStatus


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@lru_cache
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


class SqlJobRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def add(self, job: Job) -> None:
        with self.sessions.begin() as session:
            session.add(JobRow(**vars(job)))

    def get(self, job_id: UUID) -> Job | None:
        with self.sessions() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return None
            return Job(
                id=row.id,
                prompt=row.prompt,
                status=JobStatus(row.status),
                result=row.result,
                error=row.error,
                created_at=row.created_at,
            )

    def save(self, job: Job) -> None:
        with self.sessions.begin() as session:
            session.execute(
                update(JobRow)
                .where(JobRow.id == job.id)
                .values(status=job.status, result=job.result, error=job.error)
            )

    def claim(self, job_id: UUID) -> bool:
        with self.sessions.begin() as session:
            result = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.QUEUED)
                .values(status=JobStatus.RUNNING)
            )
            return result.rowcount == 1
