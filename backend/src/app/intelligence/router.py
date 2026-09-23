from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.meetings.repository import MeetingRepository, get_meetings

router = APIRouter(prefix="/api/v1/meetings", tags=["Intelligence"])


@router.post(
    "/{meeting_id}/analyze",
    responses={501: {"description": "Analysis generation is not implemented"}},
)
def analyze(meeting_id: UUID, repository: Annotated[MeetingRepository, Depends(get_meetings)]):
    repository.get(meeting_id)
    raise HTTPException(
        501,
        {
            "code": "meeting_analysis_unavailable",
            "message": "Summary and task generation is not implemented",
        },
    )
