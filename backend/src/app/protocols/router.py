from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.meetings.repository import MeetingRepository, get_meetings
from app.meetings.schemas import Input


class ExportRequest(Input):
    format: Literal["pdf", "docx"]


router = APIRouter(prefix="/api/v1/meetings", tags=["Protocols"])


@router.post("/{meeting_id}/exports", responses={501: {"description": "Export is not implemented"}})
def export_protocol(
    meeting_id: UUID,
    payload: ExportRequest,
    repository: Annotated[MeetingRepository, Depends(get_meetings)],
):
    repository.get(meeting_id)
    raise HTTPException(
        501,
        {"code": "protocol_export_unavailable", "message": "PDF/DOCX export is not implemented"},
    )
