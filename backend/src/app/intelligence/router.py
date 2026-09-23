import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.intelligence.dependencies import get_analysis_coordinator
from app.intelligence.pipeline.errors import AgentConfigurationError, MeetingIntelligenceError
from app.meetings.repository import MeetingRepository, get_meetings
from app.meetings.router import ResultView

router = APIRouter(prefix="/api/v1/meetings", tags=["Intelligence"])


@router.post(
    "/{meeting_id}/analyze",
    response_model=ResultView,
    responses={
        200: {"description": "Current meeting result, same shape as GET /result"},
        409: {"description": "Current speech/canonical transcript is missing or changed"},
        429: {"description": "Analysis capacity busy"},
        502: {"description": "Invalid agent output"},
        503: {"description": "Analysis disabled, not configured or provider unavailable"},
    },
)
async def analyze(
    meeting_id: UUID,
    repository: Annotated[MeetingRepository, Depends(get_meetings)],
    coordinator=Depends(get_analysis_coordinator),
):
    await asyncio.to_thread(repository.get, meeting_id)
    try:
        if coordinator is None:
            raise AgentConfigurationError
        return await coordinator.analyze(meeting_id)
    except MeetingIntelligenceError as exc:
        raise HTTPException(exc.http_status, {"code": exc.code, "message": exc.message}) from None
