import hashlib

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.canonicalization.models import CanonicalTranscript
from app.canonicalization.repository import CanonicalTranscriptRecord
from app.infrastructure.database import get_engine
from app.intelligence.models import Decision, MeetingAnalysis
from app.meetings.models import Meeting, Participant
from app.meetings.repository import latest_transcript
from app.protocols.errors import (
    MeetingProtocolNotReadyError,
    ProtocolExportError,
    ProtocolMeetingNotFoundError,
)
from app.protocols.models import (
    MeetingProtocol,
    ProtocolAction,
    ProtocolDecision,
    ProtocolParticipant,
    ProtocolSegment,
)
from app.speech.models import AttributedTranscript
from app.tasks.models import Task
from app.tasks.repository import task_view


class ProtocolLoader:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else get_engine()

    def load(self, meeting_id) -> MeetingProtocol:
        try:
            # One consistent PostgreSQL snapshot for names, tasks and their source transcript.
            engine = (
                self.engine.execution_options(isolation_level="REPEATABLE READ")
                if self.engine.dialect.name == "postgresql"
                else self.engine
            )
            with sessionmaker(bind=engine).begin() as session:
                return self._load(session, meeting_id)
        except (SQLAlchemyError, ValidationError, KeyError, ValueError):
            raise ProtocolExportError from None

    def _load(self, session, meeting_id):
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise ProtocolMeetingNotFoundError
        record = latest_transcript(session, meeting_id)
        analysis = session.get(MeetingAnalysis, record.id) if record else None
        if record is None or analysis is None:
            raise MeetingProtocolNotReadyError
        original = AttributedTranscript.model_validate(record.payload)
        source_hash = hashlib.sha256(original.model_dump_json().encode()).hexdigest()
        canonical_record = session.scalar(
            select(CanonicalTranscriptRecord)
            .where(
                CanonicalTranscriptRecord.source_audio_id == original.source_audio_id,
                CanonicalTranscriptRecord.source_hash == source_hash,
            )
            .order_by(
                CanonicalTranscriptRecord.created_at.desc(), CanonicalTranscriptRecord.id.desc()
            )
            .limit(1)
        )
        canonical = {}
        if canonical_record:
            result = CanonicalTranscript.model_validate(canonical_record.payload)
            canonical = {x.id: x for x in result.segments}
            if result.source_audio_id != original.source_audio_id or set(canonical) != {
                x.id for x in original.segments
            }:
                raise ProtocolExportError
            for seg in original.segments:
                item = canonical[seg.id]
                if (item.start, item.end, item.speaker_id, item.original_text) != (
                    seg.start,
                    seg.end,
                    seg.speaker_id,
                    seg.text,
                ):
                    raise ProtocolExportError
        people = list(
            session.scalars(
                select(Participant)
                .where(Participant.transcript_id == record.id)
                .order_by(Participant.speaker_id)
            )
        )
        names = {p.speaker_id: p.display_name for p in people}
        decisions = session.scalars(
            select(Decision).where(Decision.transcript_id == record.id).order_by(Decision.id)
        )
        # Manual meeting-level tasks are included; stale tasks from another transcript are excluded.
        tasks = session.scalars(
            select(Task)
            .where(
                Task.meeting_id == meeting_id,
                (Task.transcript_id == record.id) | Task.transcript_id.is_(None),
            )
            .order_by(Task.created_at, Task.id)
        )
        actions = []
        for task in tasks:
            view = task_view(session, task)
            actions.append(
                ProtocolAction(
                    text=view.text,
                    assignee=view.assignee.display_name if view.assignee else None,
                    deadline=view.due_at.isoformat() if view.due_at else None,
                    status=view.status,
                    source_segment_ids=tuple(str(x) for x in view.source_segment_ids),
                )
            )
        return MeetingProtocol(
            meeting_id=meeting.id,
            source_transcript_id=record.id,
            title=meeting.title,
            scheduled_at=meeting.scheduled_at,
            participants=tuple(
                ProtocolParticipant(speaker_id=p.speaker_id, participant_name=p.display_name)
                for p in people
            ),
            summary=analysis.summary,
            decisions=tuple(
                ProtocolDecision(text=d.text, source_segment_ids=tuple(d.source_segment_ids))
                for d in decisions
            ),
            action_items=tuple(actions),
            transcript=tuple(
                ProtocolSegment(
                    id=x.id,
                    start=x.start,
                    speaker_id=x.speaker_id,
                    participant_name=names.get(x.speaker_id),
                    original_text=x.text,
                    canonical_text=canonical[x.id].canonical_text if canonical else None,
                )
                for x in original.segments
            ),
        )
