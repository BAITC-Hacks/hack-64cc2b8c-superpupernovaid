import asyncio
import hashlib
import logging
import math
import time
from datetime import UTC, datetime
from tempfile import TemporaryFile
from threading import BoundedSemaphore
from uuid import uuid4

from app.application.ports import FileStorage, FileStorageError, FileStorageNotFoundError
from app.audio.config import AudioProcessingConfig
from app.audio.converter import AudioConverter
from app.audio.errors import (
    AudioConversionError,
    AudioProcessingBusyError,
    AudioProcessingError,
    AudioStreamNotFoundError,
    NormalizedAudioStorageError,
    UnsupportedAudioError,
)
from app.audio.models import NormalizedAudio
from app.audio.repository import AudioRepository
from app.media.models import MediaAsset, MediaStatus
from app.media.validation import CHUNK_SIZE

logger = logging.getLogger(__name__)


class AudioPreprocessor:
    def __init__(
        self,
        storage: FileStorage,
        converter: AudioConverter,
        repository: AudioRepository,
        config: AudioProcessingConfig,
        max_concurrency: int = 1,
        tracker=None,
    ):
        self.storage, self.converter = storage, converter
        self.repository, self.config = repository, config
        self.capacity = BoundedSemaphore(max_concurrency)
        self.tracker = tracker

    async def process(self, media: MediaAsset) -> NormalizedAudio:
        # Reject overload before scheduling blocking work. No unbounded work queue.
        if not self.capacity.acquire(blocking=False):
            raise AudioProcessingBusyError
        task = asyncio.create_task(asyncio.to_thread(self._run_with_slot, media))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A disconnected client must not release capacity while FFmpeg is still running.
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
            raise

    def _run_with_slot(self, media: MediaAsset) -> NormalizedAudio:
        try:
            if self.tracker:
                self.tracker.update(media.id, "preprocessing", "running")
            result = self._process(media)
            if self.tracker:
                self.tracker.update(media.id, "preprocessing", "completed")
            return result
        except Exception:
            if self.tracker:
                self.tracker.update(media.id, "preprocessing", "failed")
            raise
        finally:
            self.capacity.release()

    def _cached(self, media: MediaAsset) -> NormalizedAudio | None:
        cached = self.repository.find(media.id, self.config.fingerprint)
        if cached is None:
            return None
        try:
            size = 0
            digest = hashlib.sha256()
            with self.storage.open(cached.storage_key) as stream:
                while chunk := stream.read(CHUNK_SIZE):
                    digest.update(chunk)
                    size += len(chunk)
            if size == cached.size_bytes and digest.hexdigest() == cached.sha256:
                return cached
        except FileStorageNotFoundError:
            pass
        # Missing or corrupt derived files can be rebuilt; transient storage failures cannot.
        self.repository.remove(cached.id)
        self.storage.delete(cached.storage_key)
        logger.warning("audio_cache_invalid media_id=%s artifact=%s", media.id, cached.storage_key)
        return None

    def _delete(self, key: str, media: MediaAsset) -> None:
        try:
            self.storage.delete(key)
        except FileStorageError:
            logger.error("audio_cleanup_failed media_id=%s artifact=%s", media.id, key)

    def _process(self, media: MediaAsset) -> NormalizedAudio:
        start = time.monotonic()
        saved_key = None
        try:
            if media.status != MediaStatus.UPLOADED:
                raise UnsupportedAudioError
            if not media.audio_codec:
                raise AudioStreamNotFoundError
            cached = self._cached(media)
            if cached is not None:
                logger.info("audio_cache_hit media_id=%s artifact=%s", media.id, cached.storage_key)
                return cached
            logger.info(
                "audio_start media_id=%s source_duration=%s source_codec=%s target=%s",
                media.id,
                media.duration_seconds,
                media.audio_codec,
                self.config.model_dump(),
            )
            artifact_id = uuid4()
            key = (
                f"{media.meeting_id}/{media.id}/processed/{self.config.fingerprint}/"
                f"{artifact_id}/speech_input.{self.config.format}"
            )
            with TemporaryFile() as output:
                with self.storage.open(media.storage_key) as source:
                    info = self.converter.convert(source, output, self.config)
                if (
                    (info.sample_rate, info.channels, info.codec, info.format)
                    != (
                        self.config.sample_rate,
                        self.config.channels,
                        self.config.codec,
                        self.config.format,
                    )
                    or not math.isfinite(info.duration_seconds)
                    or info.duration_seconds <= 0
                ):
                    raise AudioConversionError
                output.seek(0)
                digest = hashlib.sha256()
                count = 0

                def chunks():
                    nonlocal count
                    while chunk := output.read(CHUNK_SIZE):
                        digest.update(chunk)
                        count += len(chunk)
                        yield chunk
                    if count == 0:
                        raise AudioConversionError

                size = self.storage.save(key, chunks(), self.config.mime_type)
                saved_key = key
            if size != count:
                raise AudioConversionError
            audio = NormalizedAudio(
                id=artifact_id,
                source_media_id=media.id,
                config_hash=self.config.fingerprint,
                storage_key=key,
                sample_rate=info.sample_rate,
                channels=info.channels,
                codec=info.codec,
                format=info.format,
                duration_seconds=info.duration_seconds,
                size_bytes=size,
                sha256=digest.hexdigest(),
                created_at=datetime.now(UTC),
            )
            result = self.repository.add_or_get(audio)
            if result.id != audio.id:
                self._delete(key, media)
            saved_key = None  # Published, or a concurrent result won; do not delete that result.
            logger.info(
                "audio_done media_id=%s elapsed_seconds=%.3f artifact=%s size_bytes=%s",
                media.id,
                time.monotonic() - start,
                result.storage_key,
                result.size_bytes,
            )
            return result
        except (AudioProcessingError, FileStorageError, OSError) as exc:
            if saved_key:
                self._delete(saved_key, media)
            logger.warning(
                "audio_failed media_id=%s elapsed_seconds=%.3f error=%s",
                media.id,
                time.monotonic() - start,
                type(exc).__name__,
            )
            if isinstance(exc, (FileStorageError, OSError)):
                raise NormalizedAudioStorageError from exc
            raise
