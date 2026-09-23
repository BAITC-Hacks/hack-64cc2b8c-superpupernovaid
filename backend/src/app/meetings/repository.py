import base64
import json
from datetime import datetime
from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import sessionmaker

from app.audio.models import NormalizedAudio
from app.infrastructure.database import get_engine
from app.intelligence.models import Decision, MeetingAnalysis
from app.media.models import MediaAsset
from app.meetings.identifiers import segment_uuid
from app.meetings.models import (
    ChangeAudit,
    Meeting,
    Participant,
    ProcessingStep,
    RecordingConsent,
    now,
)
from app.meetings.schemas import MeetingView, ParticipantView, ProcessingView, StepView
from app.speech.repository import TranscriptRecord


def cursor_encode(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def cursor_decode(value):
    try:
        if len(value) > 1024:
            raise ValueError
        return json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(422, "Invalid cursor") from None


def page_after(query, column, cursor):
    if cursor:
        try:
            ident = UUID(cursor_decode(cursor))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(422, "Invalid cursor") from None
        query = query.where(column > ident)
    return query.order_by(column)


def latest_media(session, meeting_id):
    return session.scalar(
        select(MediaAsset)
        .where(MediaAsset.meeting_id == meeting_id)
        .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        .limit(1)
    )


def latest_transcript(session, meeting_id):
    media = latest_media(session, meeting_id)
    if media is None:
        return None
    return session.scalar(
        select(TranscriptRecord)
        .join(NormalizedAudio, TranscriptRecord.source_audio_id == NormalizedAudio.id)
        .where(NormalizedAudio.source_media_id == media.id)
        .order_by(TranscriptRecord.created_at.desc(), TranscriptRecord.id.desc())
        .limit(1)
    )


def require_meeting(session, meeting_id):
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    return meeting


def meeting_view(session, row):
    media = latest_media(session, row.id)
    consent = session.scalar(
        select(RecordingConsent)
        .where(RecordingConsent.meeting_id == row.id)
        .order_by(RecordingConsent.created_at.desc(), RecordingConsent.id.desc())
        .limit(1)
    )
    return MeetingView(
        id=row.id,
        title=row.title,
        scheduled_at=row.scheduled_at,
        duration_seconds=media.duration_seconds if media else None,
        language_hint=row.language_hint,
        expected_participant_count=row.expected_participant_count,
        recording_consent_confirmed=consent.confirmed
        if consent and consent.source != "legacy_unknown"
        else None,
        processing_status=row.processing_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def ensure_participants(session, record, meeting_id):
    known = set(
        session.scalars(
            select(Participant.speaker_id).where(Participant.transcript_id == record.id)
        )
    )
    for speaker in sorted(
        {s["speaker_id"] for s in record.payload["segments"]} - {"UNKNOWN"} - known
    ):
        session.add(
            Participant(
                id=uuid4(),
                meeting_id=meeting_id,
                transcript_id=record.id,
                speaker_id=speaker,
                display_name=None,
            )
        )


class MeetingRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(
            bind=engine if engine is not None else get_engine(), expire_on_commit=False
        )

    def create(self, payload):
        with self.sessions.begin() as s:
            row = Meeting(id=uuid4(), **payload.model_dump(exclude={"recording_consent_confirmed"}))
            s.add(row)
            s.flush()
            s.add(
                RecordingConsent(
                    meeting_id=row.id,
                    confirmed=payload.recording_consent_confirmed,
                    source="user_confirmation",
                )
            )
            s.flush()
            return meeting_view(s, row)

    def get(self, ident):
        with self.sessions() as s:
            return meeting_view(s, require_meeting(s, ident))

    def list(self, cursor, limit, status):
        with self.sessions() as s:
            query = select(Meeting)
            if status:
                query = query.where(Meeting.processing_status == status)
            if cursor:
                value = cursor_decode(cursor)
                try:
                    created_at = datetime.fromisoformat(value["created_at"])
                    ident = UUID(value["id"])
                except (ValueError, TypeError, KeyError):
                    raise HTTPException(422, "Invalid cursor") from None
                query = query.where(
                    or_(
                        Meeting.created_at < created_at,
                        and_(Meeting.created_at == created_at, Meeting.id < ident),
                    )
                )
            query = query.order_by(Meeting.created_at.desc(), Meeting.id.desc())
            rows = list(s.scalars(query.limit(limit + 1)))
            return {
                "items": [meeting_view(s, r) for r in rows[:limit]],
                "next_cursor": cursor_encode(
                    {
                        "created_at": rows[limit - 1].created_at.isoformat(),
                        "id": str(rows[limit - 1].id),
                    }
                )
                if len(rows) > limit
                else None,
            }

    def patch(self, ident, payload):
        with self.sessions.begin() as s:
            row = require_meeting(s, ident)
            changes = payload.model_dump(exclude_unset=True)
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = now()
            s.add(
                ChangeAudit(
                    meeting_id=ident,
                    entity_id=ident,
                    action="meeting.patch",
                    changes=payload.model_dump(mode="json", exclude_unset=True),
                )
            )
            s.flush()
            return meeting_view(s, row)

    def participants(self, session, record):
        if record is None:
            return []
        durations = {}
        for seg in record.payload["segments"]:
            durations[seg["speaker_id"]] = (
                durations.get(seg["speaker_id"], 0) + seg["end"] - seg["start"]
            )
        total = sum(durations.values())
        rows = session.scalars(
            select(Participant)
            .where(Participant.transcript_id == record.id)
            .order_by(Participant.speaker_id)
        )
        return [
            ParticipantView(
                id=r.id,
                speaker_id=r.speaker_id,
                display_name=r.display_name,
                speech_share=durations.get(r.speaker_id, 0) / total if total else None,
            )
            for r in rows
        ]

    def rename_participant(self, ident, speaker, payload):
        with self.sessions.begin() as s:
            require_meeting(s, ident)
            record = latest_transcript(s, ident)
            row = (
                s.scalar(
                    select(Participant).where(
                        Participant.transcript_id == record.id, Participant.speaker_id == speaker
                    )
                )
                if record
                else None
            )
            if row is None:
                raise HTTPException(404, "Speaker not found in current transcript")
            if "display_name" in payload.model_fields_set:
                row.display_name = payload.display_name
                s.add(
                    ChangeAudit(
                        meeting_id=ident,
                        entity_id=row.id,
                        action="participant.patch",
                        changes=payload.model_dump(mode="json", exclude_unset=True),
                    )
                )
            s.flush()
            return next(p for p in self.participants(s, record) if p.id == row.id)

    def transcript(self, ident, cursor, limit, q):
        with self.sessions() as s:
            require_meeting(s, ident)
            record = latest_transcript(s, ident)
            if record is None:
                return {"items": [], "next_cursor": None}
            offset = 0
            if cursor:
                value = cursor_decode(cursor)
                if (
                    not isinstance(value, dict)
                    or value.get("version") != str(record.id)
                    or value.get("q") != q
                ):
                    raise HTTPException(409, "Transcript or query changed; restart pagination")
                offset = value.get("offset")
                if type(offset) is not int or offset < 0:
                    raise HTTPException(422, "Invalid cursor")
            segments = [
                x
                for x in record.payload["segments"]
                if not q or q.casefold() in x["text"].casefold()
            ]
            items = [
                {
                    "id": segment_uuid(x["id"]),
                    "started_at_ms": round(x["start"] * 1000),
                    "ended_at_ms": round(x["end"] * 1000),
                    "speaker_id": x["speaker_id"],
                    "text": x["text"],
                    "confidence": None,
                    "language": None,
                }
                for x in segments[offset : offset + limit]
            ]
            next_cursor = (
                cursor_encode({"version": str(record.id), "q": q, "offset": offset + limit})
                if offset + limit < len(segments)
                else None
            )
            return {"items": items, "next_cursor": next_cursor}

    def processing(self, ident):
        with self.sessions() as s:
            row = require_meeting(s, ident)
            media = latest_media(s, ident)
            from app.processing.models import ProcessingRun

            run = s.get(ProcessingRun, ident)
            if run and media and run.media_id == media.id:
                return ProcessingView(
                    meeting_id=ident,
                    media_id=media.id,
                    status=(
                        "ready"
                        if run.status == "completed"
                        else "failed"
                        if run.status == "failed"
                        else "queued"
                        if run.status == "queued"
                        else run.stage or "queued"
                    ),
                    steps=[
                        StepView(
                            stage=stage,
                            status=state,
                            progress=100 if state == "completed" else None,
                            message=run.error_message if state == "failed" else state.capitalize(),
                            updated_at=run.updated_at,
                        )
                        for stage, state in run.steps.items()
                    ],
                    updated_at=run.updated_at,
                )
            saved = (
                {
                    x.stage: x
                    for x in s.scalars(
                        select(ProcessingStep).where(ProcessingStep.media_id == media.id)
                    )
                }
                if media
                else {}
            )
            audio = (
                s.scalar(
                    select(NormalizedAudio.id)
                    .where(NormalizedAudio.source_media_id == media.id)
                    .limit(1)
                )
                if media
                else None
            )
            transcript = latest_transcript(s, ident)
            analysis = s.get(MeetingAnalysis, transcript.id) if transcript else None
            completed = {
                "uploaded": media is not None,
                "preprocessing": audio is not None,
                "transcribing": transcript is not None,
                "diarizing": transcript is not None,
                "analyzing": analysis is not None,
            }
            steps = []
            for stage, done in completed.items():
                state = saved.get(stage)
                status = state.status if state else ("completed" if done else "pending")
                steps.append(
                    StepView(
                        stage=stage,
                        status=status,
                        progress=100 if status == "completed" else None,
                        message=state.message
                        if state
                        else ("Completed" if done else "Not started"),
                        updated_at=state.updated_at if state else row.updated_at,
                    )
                )
            return ProcessingView(
                meeting_id=ident,
                media_id=media.id if media else None,
                status=row.processing_status,
                steps=steps,
                updated_at=row.updated_at,
            )

    def result(self, ident):
        from app.tasks.models import Task
        from app.tasks.repository import task_view
        from app.tasks.visibility import active_tasks

        with self.sessions() as s:
            meeting = require_meeting(s, ident)
            record = latest_transcript(s, ident)
            analysis = s.get(MeetingAnalysis, record.id) if record else None
            decisions = (
                list(s.scalars(select(Decision).where(Decision.transcript_id == record.id)))
                if analysis
                else []
            )
            tasks = s.scalars(
                select(Task).where(Task.meeting_id == ident, active_tasks())
                .order_by(Task.created_at, Task.id)
            )
            return {
                "meeting": meeting_view(s, meeting),
                "participants": self.participants(s, record),
                "summary": analysis.summary if analysis else None,
                "analysis_details": analysis.details if analysis else None,
                "decisions": [
                    {"id": r.id, "text": r.text, "source_segment_ids": r.source_segment_ids}
                    for r in decisions
                ],
                "tasks": [task_view(s, r) for r in tasks],
            }


@lru_cache
def get_meetings():
    return MeetingRepository()
