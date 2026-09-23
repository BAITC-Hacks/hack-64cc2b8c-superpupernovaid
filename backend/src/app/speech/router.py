from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.audio.errors import AudioProcessingError
from app.audio.repository import AudioRepository
from app.bootstrap import get_media_repository
from app.config import Settings, get_settings
from app.media.errors import MediaError
from app.media.repository import MediaRepository
from app.speech.dependencies import get_speech_audio_repository, get_speech_service
from app.speech.errors import SpeechDisabledError, SpeechProcessingError
from app.speech.models import AttributedTranscript
from app.speech.service import SpeechService

router = APIRouter(prefix="/api/v1/meetings/{meeting_id}/media", tags=["Speech"])


@router.post(
    "/{media_id}/speech",
    response_model=AttributedTranscript,
    summary="Recognize and attribute speech from already normalized audio",
    responses={
        404: {"description": "Media not found"},
        409: {"description": "Preprocessing required for current audio configuration"},
        413: {"description": "Normalized audio exceeds cloud request limit"},
        422: {"description": "Invalid audio or speech output"},
        429: {"description": "Speech capacity is busy"},
        502: {"description": "NVIDIA cloud request failed"},
        503: {"description": "Speech disabled or local resources unavailable"},
    },
)
async def process_speech(
    meeting_id: UUID,
    media_id: UUID,
    media_repository: Annotated[MediaRepository, Depends(get_media_repository)],
    audio_repository: Annotated[AudioRepository, Depends(get_speech_audio_repository)],
    service: Annotated[SpeechService | None, Depends(get_speech_service)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    try:
        media = await run_in_threadpool(media_repository.get, meeting_id, media_id)
        if media is None:
            raise HTTPException(404, "Media asset not found")
        audio = await run_in_threadpool(
            audio_repository.find, media.id, settings.audio_processing_config.fingerprint
        )
        if audio is None:
            raise HTTPException(
                409,
                {
                    "code": "audio_preprocessing_required",
                    "message": "Preprocess media with current audio settings first",
                },
            )
        if service is None:
            raise SpeechDisabledError
        return await service.process(audio)
    except (SpeechProcessingError, AudioProcessingError, MediaError) as exc:
        raise HTTPException(
            exc.http_status,
            {"code": exc.code, "message": exc.message},
            headers={"Retry-After": "5"} if exc.http_status == 429 else None,
        ) from None
