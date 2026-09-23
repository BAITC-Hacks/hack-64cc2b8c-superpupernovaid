import asyncio
import hashlib
import json
import logging
import shutil
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from threading import BoundedSemaphore
from uuid import uuid4

from app.application.ports import FileStorage, FileStorageError, FileStorageNotFoundError
from app.protocols.errors import (
    ProtocolArtifactStorageError,
    ProtocolExportBusyError,
    ProtocolExportError,
    ProtocolExportTooLargeError,
    UnsupportedExportFormatError,
)
from app.protocols.interfaces import ProtocolRenderer
from app.protocols.models import MIME_TYPES, ExportedDocument, MeetingProtocol
from app.protocols.repository import ExportRepository

logger = logging.getLogger(__name__)
CHUNK_SIZE = 64 * 1024


def chunks(path):
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            yield chunk


class ProtocolExportService:
    def __init__(
        self,
        renderers: Mapping[str, ProtocolRenderer],
        storage: FileStorage,
        repository: ExportRepository,
        max_characters: int = 2_000_000,
        max_bytes: int = 50 * 1024**2,
    ):
        self.renderers, self.storage, self.repository = renderers, storage, repository
        self.max_characters, self.max_bytes = max_characters, max_bytes
        self.capacity = BoundedSemaphore(1)
        self.tasks = set()
        self.closing = False

    def _hash(self, protocol, renderer):
        data = protocol.model_dump(mode="json")
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) > self.max_characters:
            raise ProtocolExportTooLargeError
        return hashlib.sha256((renderer.revision + "\n" + encoded).encode()).hexdigest()

    async def export(self, protocol: MeetingProtocol, format: str) -> ExportedDocument:
        if format not in self.renderers:
            raise UnsupportedExportFormatError
        if self.closing or not self.capacity.acquire(blocking=False):
            raise ProtocolExportBusyError
        task = asyncio.create_task(self._run(protocol, format))
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _valid(self, artifact):
        try:
            total, digest = 0, hashlib.sha256()
            with self.storage.open(artifact.storage_key) as stream:
                while block := stream.read(CHUNK_SIZE):
                    total += len(block)
                    if total > min(artifact.size_bytes, self.max_bytes):
                        return False
                    digest.update(block)
            return total == artifact.size_bytes and digest.hexdigest() == artifact.sha256
        except FileStorageNotFoundError:
            return False
        except FileStorageError:
            raise ProtocolArtifactStorageError from None

    def _publish(self, protocol, format, hash_value, path):
        size = path.stat().st_size
        if size <= 0 or size > self.max_bytes:
            raise ProtocolExportTooLargeError
        digest = hashlib.sha256()
        for block in chunks(path):
            digest.update(block)
        ident = uuid4()
        filename = f"meeting_{protocol.meeting_id}_protocol.{format}"
        key = f"{protocol.meeting_id}/exports/{hash_value}/{ident}.{format}"
        saved = False
        try:
            stored_size = self.storage.save(key, chunks(path), MIME_TYPES[format])
            saved = True
            if stored_size != size:
                raise ProtocolArtifactStorageError
            artifact = ExportedDocument(
                id=ident,
                meeting_id=protocol.meeting_id,
                format=format,
                filename=filename,
                storage_key=key,
                size_bytes=size,
                sha256=digest.hexdigest(),
                protocol_hash=hash_value,
                created_at=datetime.now(UTC),
            )
            winner = self.repository.add_or_get(artifact)
            if winner.id != artifact.id:
                self.storage.delete(key)
            return winner
        except Exception:
            if saved:
                self.storage.delete(key)
            raise

    async def _run(self, protocol, format):
        start = time.monotonic()
        try:
            renderer = self.renderers[format]
            hash_value = await asyncio.to_thread(self._hash, protocol, renderer)
            cached = await asyncio.to_thread(
                self.repository.find, protocol.meeting_id, hash_value, format
            )
            if cached:
                if await asyncio.to_thread(self._valid, cached):
                    return cached
                await asyncio.to_thread(self.repository.remove, cached.id)
                await asyncio.to_thread(self.storage.delete, cached.storage_key)
            with TemporaryDirectory(prefix="protocol-render-") as folder:
                path = Path(folder) / ("protocol." + format)
                await renderer.render(protocol, path)
                artifact = await asyncio.to_thread(
                    self._publish, protocol, format, hash_value, path
                )
            logger.info(
                "protocol_exported meeting_id=%s format=%s artifact_id=%s size=%s elapsed=%.3f",
                protocol.meeting_id,
                format,
                artifact.id,
                artifact.size_bytes,
                time.monotonic() - start,
            )
            return artifact
        except ProtocolExportError:
            raise
        except (FileStorageError, OSError):
            raise ProtocolArtifactStorageError from None
        except Exception:
            raise ProtocolExportError from None
        finally:
            self.capacity.release()

    def prepare_download(self, artifact: ExportedDocument) -> Path:
        # Spool to disk before sending HTTP headers, so storage errors stay controlled.
        folder = Path(mkdtemp(prefix="protocol-download-"))
        path = folder / artifact.filename
        try:
            total, digest = 0, hashlib.sha256()
            with self.storage.open(artifact.storage_key) as source, path.open("wb") as target:
                while block := source.read(CHUNK_SIZE):
                    total += len(block)
                    if total > min(self.max_bytes, artifact.size_bytes):
                        raise ProtocolArtifactStorageError
                    digest.update(block)
                    target.write(block)
            if total != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                raise ProtocolArtifactStorageError
            return path
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise ProtocolArtifactStorageError from None

    async def close(self):
        self.closing = True
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
