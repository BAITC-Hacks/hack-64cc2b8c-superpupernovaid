"""Atomic publication boundary for a future analyzer; no LLM invocation here."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import get_engine
from app.intelligence.models import Decision, MeetingAnalysis
from app.meetings.identifiers import segment_uuid
from app.meetings.models import ChangeAudit, now
from app.meetings.repository import latest_transcript, require_meeting
from app.meetings.schemas import Input
from app.tasks.models import Task
from app.tasks.repository import check_assignee
from app.tasks.schemas import TaskCreate


class DecisionInput(Input):
    text: str = Field(min_length=1, max_length=10000)
    source_segment_ids: list[UUID] = Field(min_length=1, max_length=100)


class AnalysisInput(Input):
    transcript_id: UUID
    summary: str = Field(min_length=1, max_length=50000)
    decisions: list[DecisionInput] = Field(default_factory=list, max_length=100)
    tasks: list[TaskCreate] = Field(default_factory=list, max_length=100)


class AnalysisRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def publish(self, meeting_id, payload: AnalysisInput):
        with self.sessions.begin() as s:
            meeting = require_meeting(s, meeting_id)
            record = latest_transcript(s, meeting_id)
            if record is None or record.id != payload.transcript_id:
                raise HTTPException(409, "Analysis must use the current transcript")
            if s.get(MeetingAnalysis, record.id):
                raise HTTPException(409, "Analysis already published for this transcript")
            allowed = {str(segment_uuid(seg["id"])) for seg in record.payload["segments"]}
            for item in [*payload.decisions, *payload.tasks]:
                if (
                    not item.source_segment_ids
                    or not {str(x) for x in item.source_segment_ids} <= allowed
                ):
                    raise HTTPException(
                        422, "Generated items require valid source segment references"
                    )
            for task in payload.tasks:
                check_assignee(s, meeting_id, task.assignee_id)
            s.add(MeetingAnalysis(transcript_id=record.id, summary=payload.summary))
            s.flush()
            for decision in payload.decisions:
                s.add(
                    Decision(
                        transcript_id=record.id,
                        text=decision.text,
                        source_segment_ids=[str(x) for x in decision.source_segment_ids],
                    )
                )
            for task in payload.tasks:
                s.add(
                    Task(
                        meeting_id=meeting_id,
                        transcript_id=record.id,
                        text=task.text,
                        assignee_id=task.assignee_id,
                        due_at=task.due_at,
                        priority=task.priority,
                        source_segment_ids=[str(x) for x in task.source_segment_ids],
                    )
                )
            meeting.processing_status = "ready"
            meeting.updated_at = now()
            s.add(
                ChangeAudit(
                    meeting_id=meeting_id,
                    entity_id=record.id,
                    action="analysis.publish",
                    changes={"decisions": len(payload.decisions), "tasks": len(payload.tasks)},
                )
            )
