from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.meetings.repository import MeetingRepository, get_meetings
from app.meetings.schemas import (
    MeetingCreate,
    MeetingPage,
    MeetingPatch,
    MeetingView,
    ParticipantPatch,
    ParticipantView,
    ProcessingView,
    Status,
    TranscriptPage,
)
from app.tasks.schemas import TaskView


class DecisionView(BaseModel):
    id: UUID
    text: str
    source_segment_ids: list[UUID]


class ResultView(BaseModel):
    meeting: MeetingView
    participants: list[ParticipantView]
    summary: str | None
    decisions: list[DecisionView]
    tasks: list[TaskView]


router = APIRouter(prefix="/api/v1/meetings", tags=["Meetings"])
Repo = Annotated[MeetingRepository, Depends(get_meetings)]


@router.post("", response_model=MeetingView, status_code=201)
def create_meeting(payload: MeetingCreate, repository: Repo):
    return repository.create(payload)


@router.get("", response_model=MeetingPage)
def list_meetings(
    repository: Repo,
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(50, ge=1, le=100),
    status: Status | None = None,
):
    return repository.list(cursor, limit, status)


@router.get("/{meeting_id}", response_model=MeetingView)
def read_meeting(meeting_id: UUID, repository: Repo):
    return repository.get(meeting_id)


@router.patch("/{meeting_id}", response_model=MeetingView)
def patch_meeting(meeting_id: UUID, payload: MeetingPatch, repository: Repo):
    return repository.patch(meeting_id, payload)


@router.get("/{meeting_id}/processing", response_model=ProcessingView)
def processing(meeting_id: UUID, repository: Repo):
    return repository.processing(meeting_id)


@router.get("/{meeting_id}/result", response_model=ResultView)
def result(meeting_id: UUID, repository: Repo):
    return repository.result(meeting_id)


@router.get("/{meeting_id}/transcript", response_model=TranscriptPage)
def transcript(
    meeting_id: UUID,
    repository: Repo,
    cursor: str | None = Query(None, max_length=1024),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=100),
):
    return repository.transcript(meeting_id, cursor, limit, q)


@router.patch("/{meeting_id}/participants/{speaker_id}", response_model=ParticipantView)
def rename_participant(
    meeting_id: UUID, speaker_id: str, payload: ParticipantPatch, repository: Repo
):
    return repository.rename_participant(meeting_id, speaker_id, payload)
