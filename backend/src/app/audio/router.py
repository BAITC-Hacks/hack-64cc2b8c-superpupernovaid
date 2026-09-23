from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.audio.errors import AudioProcessingError
from app.audio.models import NormalizedAudioResponse
from app.audio.service import AudioPreprocessor
from app.bootstrap import get_audio_preprocessor, get_media_repository
from app.media.errors import MediaError
from app.media.repository import MediaRepository

router = APIRouter(prefix="/api/v1/meetings/{meeting_id}/media", tags=["Audio"])


@router.post(
    "/{media_id}/preprocess",
    response_model=NormalizedAudioResponse,
    summary="Prepare canonical audio from a saved recording",
    responses={
        404: {"description": "Media asset not found"},
        422: {"description": "No audio or conversion failed"},
        429: {"description": "Processing capacity is busy"},
        503: {"description": "Storage, database or tools unavailable"},
        504: {"description": "Processing timeout"},
    },
)
async def preprocess_audio(
    meeting_id: UUID,
    media_id: UUID,
    repository: Annotated[MediaRepository, Depends(get_media_repository)],
    preprocessor: Annotated[AudioPreprocessor, Depends(get_audio_preprocessor)],
):
    try:
        media = await run_in_threadpool(repository.get, meeting_id, media_id)
        if media is None:
            raise HTTPException(404, "Media asset not found")
        return await preprocessor.process(media)
    except (AudioProcessingError, MediaError) as exc:
        raise HTTPException(
            exc.http_status,
            {"code": exc.code, "message": exc.message},
            headers={"Retry-After": "5"} if exc.http_status == 429 else None,
        ) from None
