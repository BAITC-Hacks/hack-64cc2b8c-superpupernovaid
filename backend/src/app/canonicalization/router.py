from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.audio.errors import AudioProcessingError
from app.audio.repository import AudioRepository
from app.bootstrap import get_media_repository
from app.canonicalization.dependencies import (
    get_canonicalization_service,
    get_canonicalization_speech_repository,
)
from app.canonicalization.errors import (
    CanonicalizationConfigurationError,
    TranscriptCanonicalizationError,
)
from app.canonicalization.models import CanonicalTranscript
from app.canonicalization.service import TranscriptCanonicalizationService
from app.config import Settings, get_settings
from app.media.errors import MediaError
from app.media.repository import MediaRepository
from app.speech.dependencies import get_speech_audio_repository, speech_profile
from app.speech.errors import SpeechProcessingError
from app.speech.repository import SpeechRepository

router = APIRouter(prefix="/api/v1/meetings/{meeting_id}/media", tags=["Canonicalization"])


@router.post(
    "/{media_id}/canonicalize",
    response_model=CanonicalTranscript,
    summary="Canonicalize an existing attributed transcript into one configured language",
    responses={
        404: {"description": "Media not found"},
        409: {"description": "Current audio or speech result not ready"},
        422: {"description": "Segment exceeds input budget"},
        429: {"description": "Canonicalization capacity busy"},
        502: {"description": "Invalid or incomplete model output"},
        503: {"description": "Disabled, unconfigured or provider unavailable"},
    },
)
async def canonicalize_transcript(
    meeting_id: UUID,
    media_id: UUID,
    media_repository: Annotated[MediaRepository, Depends(get_media_repository)],
    audio_repository: Annotated[AudioRepository, Depends(get_speech_audio_repository)],
    speech_repository: Annotated[SpeechRepository, Depends(get_canonicalization_speech_repository)],
    service: Annotated[
        TranscriptCanonicalizationService | None, Depends(get_canonicalization_service)
    ],
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
            raise HTTPException(409, {"code": "audio_preprocessing_required"})
        transcript = await run_in_threadpool(
            speech_repository.find, audio.id, speech_profile(settings)
        )
        if transcript is None:
            raise HTTPException(409, {"code": "speech_processing_required"})
        if service is None:
            raise CanonicalizationConfigurationError
        return await service.canonicalize(transcript)
    except (
        TranscriptCanonicalizationError,
        SpeechProcessingError,
        AudioProcessingError,
        MediaError,
    ) as exc:
        raise HTTPException(
            exc.http_status,
            {"code": exc.code, "message": exc.message},
            headers={"Retry-After": "5"} if exc.http_status == 429 else None,
        ) from None
