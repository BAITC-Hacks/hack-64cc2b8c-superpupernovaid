from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.intelligence.pipeline.errors import MeetingIntelligenceError
from app.processing.dependencies import get_processing_repository, get_submit_meeting_processing
from app.processing.errors import MeetingProcessingError
from app.processing.models import ProcessRequest, RunView
from app.processing.repository import ProcessingRepository
from app.processing.service import SubmitMeetingProcessing

router = APIRouter(prefix="/api/v1/meetings", tags=["Meeting processing"])


@router.post("/{meeting_id}/process", response_model=RunView, status_code=202)
def process_meeting(
    meeting_id: UUID,
    payload: ProcessRequest,
    service: Annotated[SubmitMeetingProcessing, Depends(get_submit_meeting_processing)],
):
    try:
        return service.submit(meeting_id, payload)
    except (MeetingProcessingError, MeetingIntelligenceError) as exc:
        raise HTTPException(exc.http_status, {"code": exc.code, "message": exc.message}) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Processing database unavailable") from None


@router.get("/{meeting_id}/processing-run", response_model=RunView)
def processing_run(
    meeting_id: UUID,
    repository: Annotated[ProcessingRepository, Depends(get_processing_repository)],
):
    try:
        return repository.get(meeting_id)
    except (MeetingProcessingError, MeetingIntelligenceError) as exc:
        raise HTTPException(exc.http_status, {"code": exc.code, "message": exc.message}) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Processing database unavailable") from None
