import logging
from datetime import UTC, datetime
from typing import BinaryIO
from uuid import UUID, uuid4

from app.application.ports import FileStorage, FileStorageError
from app.media.errors import MediaError, MediaStorageError, UnsupportedMediaError
from app.media.models import MediaAsset, MediaStatus
from app.media.probe import MediaProbe
from app.media.repository import MediaRepository
from app.media.validation import display_filename, limited_chunks

logger = logging.getLogger(__name__)


class MediaService:
    def __init__(
        self,
        storage: FileStorage,
        probe: MediaProbe,
        repository: MediaRepository,
        max_bytes: int,
        allowed_formats: frozenset[str],
    ):
        self.storage, self.probe, self.repository = storage, probe, repository
        self.max_bytes, self.allowed_formats = max_bytes, allowed_formats

    def ingest(self, meeting_id: UUID, filename: str, source: BinaryIO) -> MediaAsset:
        media_id = uuid4()
        key = f"{meeting_id}/{media_id}/source"
        saved = False
        size = None
        try:
            original_filename = display_filename(filename)
            logger.info("media_save media_id=%s meeting_id=%s", media_id, meeting_id)
            size = self.storage.save(
                key, limited_chunks(source, self.max_bytes), "application/octet-stream"
            )
            saved = True
            with self.storage.open(key) as stored:
                metadata = self.probe.inspect(stored)
            if metadata.container not in self.allowed_formats:
                raise UnsupportedMediaError
            asset = MediaAsset(
                id=media_id,
                meeting_id=meeting_id,
                original_filename=original_filename,
                storage_key=key,
                size_bytes=size,
                media_type=metadata.media_type,
                mime_type=metadata.mime_type,
                duration_seconds=metadata.duration_seconds,
                container=metadata.container,
                audio_codec=metadata.audio_codec,
                video_codec=metadata.video_codec,
                status=MediaStatus.UPLOADED,
                created_at=datetime.now(UTC),
            )
            self.repository.add(asset)
            logger.info(
                "media_uploaded media_id=%s meeting_id=%s size_bytes=%s type=%s duration=%s",
                media_id,
                meeting_id,
                size,
                asset.media_type,
                asset.duration_seconds,
            )
            return asset
        except (MediaError, FileStorageError) as exc:
            logger.warning(
                "media_rejected media_id=%s meeting_id=%s size_bytes=%s error=%s",
                media_id,
                meeting_id,
                size,
                type(exc).__name__,
            )
            if saved:
                try:
                    self.storage.delete(key)
                    logger.info("media_delete media_id=%s meeting_id=%s", media_id, meeting_id)
                except FileStorageError:
                    logger.error(
                        "media_cleanup_failed media_id=%s meeting_id=%s", media_id, meeting_id
                    )
            if isinstance(exc, FileStorageError):
                raise MediaStorageError from exc
            raise
