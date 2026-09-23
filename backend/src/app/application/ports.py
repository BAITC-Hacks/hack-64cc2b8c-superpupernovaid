from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol
from uuid import UUID

from app.domain.jobs import Job


class JobRepository(Protocol):
    def add(self, job: Job) -> None: ...
    def get(self, job_id: UUID) -> Job | None: ...
    def save(self, job: Job) -> None: ...
    def claim(self, job_id: UUID) -> bool: ...


class TaskQueue(Protocol):
    def enqueue(self, job_id: UUID) -> None: ...


class AgentOrchestrator(Protocol):
    async def run(self, prompt: str) -> str: ...


class FileStorageError(Exception):
    """Storage adapters translate backend-specific failures to this exception."""


class FileStorageNotFoundError(FileStorageError):
    """The requested object is absent, not merely temporarily inaccessible."""


class FileStorage(Protocol):
    # On failure save must clean up partial writes; delete is idempotent.
    def save(self, key: str, chunks: Iterable[bytes], content_type: str) -> int: ...
    def open(self, key: str) -> AbstractContextManager[BinaryIO]: ...
    def delete(self, key: str) -> None: ...


class MailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...
