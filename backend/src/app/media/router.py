import logging
from functools import lru_cache
from threading import BoundedSemaphore
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.types import Receive, Scope, Send

from app.bootstrap import get_media_service
from app.config import get_settings
from app.media.errors import MediaError, MediaStorageError, MediaTooLargeError
from app.media.models import MediaAssetResponse, MediaErrorResponse
from app.media.service import MediaService

logger = logging.getLogger(__name__)
MULTIPART_OVERHEAD = 1024 * 1024


def error_detail(error: MediaError) -> dict[str, str]:
    return {"code": error.code, "message": error.message}


@lru_cache
def get_upload_capacity() -> BoundedSemaphore:
    return BoundedSemaphore(get_settings().media_max_concurrent_uploads)


class MediaUploadRoute(APIRoute):
    """Bound the body before multipart spooling, including chunked requests."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] != "POST":
            return await super().handle(scope, receive, send)
        capacity = get_upload_capacity()
        if not capacity.acquire(blocking=False):
            await JSONResponse(
                status_code=429,
                headers={"Retry-After": "5"},
                content={
                    "detail": {
                        "code": "media_upload_busy",
                        "message": "Upload capacity is busy. Retry later.",
                    }
                },
            )(scope, receive, send)
            return
        try:
            await self._bounded_upload(scope, receive, send)
        finally:
            capacity.release()

    async def _bounded_upload(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = get_settings().media_max_file_size_bytes + MULTIPART_OVERHEAD
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length > limit:
            logger.warning("media_request_rejected reason=body_limit size_bytes=%s", length)
            await JSONResponse(
                status_code=413, content={"detail": error_detail(MediaTooLargeError())}
            )(scope, receive, send)
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    logger.warning(
                        "media_request_rejected reason=body_limit size_bytes=%s", received
                    )
                    raise HTTPException(413, error_detail(MediaTooLargeError()))
            return message

        await super().handle(scope, limited_receive, send)

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            if request.method == "POST":
                # The cached form is reused by FastAPI's File parameter handling.
                try:
                    async with request.form(max_files=1, max_fields=0):
                        return await original(request)
                except OSError:
                    logger.error("media_request_rejected reason=multipart_storage_failure")
                    error = MediaStorageError()
                    raise HTTPException(error.http_status, error_detail(error)) from None
            return await original(request)

        return handler


router = APIRouter(
    prefix="/api/v1/meetings/{meeting_id}/media", tags=["Media"], route_class=MediaUploadRoute
)


@router.post(
    "",
    status_code=201,
    response_model=MediaAssetResponse,
    summary="Upload an original meeting recording",
    responses={code: {"model": MediaErrorResponse} for code in (413, 415, 422, 429, 503)},
)
def upload_media(
    meeting_id: UUID,
    file: Annotated[UploadFile, File()],
    service: Annotated[MediaService, Depends(get_media_service)],
):
    try:
        # Synchronous endpoint runs I/O and ffprobe outside the event loop.
        # Only a generic binary stream crosses the transport boundary.
        from app.meetings.repository import MeetingRepository

        meeting = MeetingRepository(service.repository.sessions.kw["bind"]).get(meeting_id)
        if meeting.recording_consent_confirmed is not True:
            raise HTTPException(409, "Recording consent must be confirmed before upload")
        return service.ingest(meeting_id, file.filename or "", file.file)
    except MediaError as exc:
        raise HTTPException(exc.http_status, error_detail(exc)) from None


@router.get(
    "/{media_id}",
    response_model=MediaAssetResponse,
    summary="Get a persisted media reference",
    responses={404: {"description": "Not found"}},
)
def read_media(
    meeting_id: UUID, media_id: UUID, service: Annotated[MediaService, Depends(get_media_service)]
):
    try:
        asset = service.repository.get(meeting_id, media_id)
    except MediaError as exc:
        raise HTTPException(exc.http_status, error_detail(exc)) from None
    if asset is None:
        raise HTTPException(404, "Media asset not found")
    return asset
