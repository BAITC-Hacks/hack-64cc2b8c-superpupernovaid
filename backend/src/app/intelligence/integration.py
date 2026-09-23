"""Adapt persisted meeting/UI contracts to the existing typed agent pipeline."""

import asyncio
import hashlib
from threading import BoundedSemaphore
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.canonicalization.models import CanonicalTranscript
from app.canonicalization.repository import CanonicalTranscriptRecord
from app.intelligence.models import MeetingAnalysis
from app.intelligence.pipeline.errors import (
    AgentOutputValidationError,
    AnalysisBusyError,
    AnalysisPersistenceError,
)
from app.intelligence.pipeline.models import (
    MeetingContext,
    MeetingIntelligenceInput,
    SpeakerMapping,
)
from app.intelligence.pipeline.models import (
    Participant as AgentParticipant,
)
from app.intelligence.repository import AnalysisInput, AnalysisRepository, DecisionInput
from app.meetings.identifiers import segment_uuid
from app.meetings.models import Participant
from app.meetings.progress import ProcessingTracker
from app.meetings.repository import MeetingRepository, latest_transcript, require_meeting
from app.speech.models import AttributedTranscript
from app.tasks.schemas import TaskCreate


class AnalysisCoordinator:
    def __init__(self, pipeline, engine=None):
        self.pipeline = pipeline
        self.repository = AnalysisRepository(engine)
        self.meetings = MeetingRepository(engine)
        self.tasks = set()
        self.closing = False
        self.running_transcript = None
        self.capacity = BoundedSemaphore(1)
        self.progress = ProcessingTracker(engine)

    def load(self, meeting_id):
        with self.repository.sessions() as session:
            meeting = require_meeting(session, meeting_id)
            record = latest_transcript(session, meeting_id)
            if record is None:
                raise HTTPException(409, "Speech transcript is required before analysis")
            if session.get(MeetingAnalysis, record.id):
                return record.id, None
            original = AttributedTranscript.model_validate(record.payload)
            source_hash = hashlib.sha256(original.model_dump_json().encode()).hexdigest()
            canonical = session.scalar(
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
            if canonical is None:
                raise HTTPException(409, "Canonicalize the current transcript before analysis")
            try:
                transcript = CanonicalTranscript.model_validate(canonical.payload)
                if transcript.source_audio_id != original.source_audio_id or [
                    (x.id, x.start, x.end, x.speaker_id, x.original_text)
                    for x in transcript.segments
                ] != [(x.id, x.start, x.end, x.speaker_id, x.text) for x in original.segments]:
                    raise AgentOutputValidationError
                # Match the UUIDs already exposed by GET /transcript; never edit stored artifacts.
                transcript = transcript.model_copy(
                    update={
                        "segments": [
                            x.model_copy(update={"id": str(segment_uuid(x.id))})
                            for x in transcript.segments
                        ]
                    }
                )
                if len({x.id for x in transcript.segments}) != len(transcript.segments):
                    raise AgentOutputValidationError
                people = list(
                    session.scalars(
                        select(Participant)
                        .where(Participant.transcript_id == record.id)
                        .order_by(Participant.id)
                    )
                )
                named = [p for p in people if p.display_name]
                participants = [AgentParticipant(id=str(p.id), name=p.display_name) for p in named]
                mappings = []
                for p in named:
                    evidence = next(
                        (x.id for x in transcript.segments if x.speaker_id == p.speaker_id), None
                    )
                    if evidence and p.speaker_id != "UNKNOWN":
                        mappings.append(
                            SpeakerMapping(
                                speaker_id=p.speaker_id,
                                participant_id=str(p.id),
                                status="resolved",
                                evidence_segment_ids=[evidence],
                            )
                        )
                return record.id, MeetingIntelligenceInput(
                    # scheduled_at is not an actual recording start. Do not infer relative dates.
                    meeting=MeetingContext(meeting_id=meeting_id, title=meeting.title),
                    transcript=transcript,
                    participants=participants,
                    speaker_mapping=mappings,
                )
            except ValidationError:
                raise AgentOutputValidationError from None

    async def analyze(self, meeting_id):
        if self.closing or not self.capacity.acquire(blocking=False):
            raise AnalysisBusyError
        try:
            task = asyncio.create_task(self._run(meeting_id))
        except BaseException:
            self.capacity.release()
            raise
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task):
        self.capacity.release()
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _run(self, meeting_id):
        try:
            return await self._execute(meeting_id)
        except SQLAlchemyError:
            raise AnalysisPersistenceError from None
        except BaseException:
            if self.running_transcript is not None:
                await asyncio.to_thread(self._progress, self.running_transcript, "failed")
            raise
        finally:
            self.running_transcript = None

    async def _execute(self, meeting_id):
        transcript_id, context = await asyncio.to_thread(self.load, meeting_id)
        if context is None:
            return await asyncio.to_thread(self.meetings.result, meeting_id)
        self.running_transcript = transcript_id
        await asyncio.to_thread(self._progress, transcript_id, "running")
        result = await self.pipeline.analyze(context)
        # Recheck after the model call: a new upload or renamed participants invalidates input.
        latest_id, latest_context = await asyncio.to_thread(self.load, meeting_id)
        if latest_id != transcript_id or (latest_context is not None and latest_context != context):
            raise HTTPException(409, "Meeting context changed during analysis; retry")
        if latest_context is not None:
            try:
                payload = AnalysisInput(
                    transcript_id=transcript_id,
                    summary=result.summary,
                    decisions=[DecisionInput(**d.model_dump()) for d in result.decisions],
                    tasks=[
                        TaskCreate(
                            text=a.task,
                            assignee_id=UUID(a.assignee_participant_id)
                            if a.assignee_participant_id
                            else None,
                            # Agents return dates, UI needs an instant. Preserve date in details
                            # until the user supplies a time/zone.
                            due_at=None,
                            source_segment_ids=a.source_segment_ids,
                        )
                        for a in result.action_items
                    ],
                )
            except (ValidationError, ValueError):
                raise AgentOutputValidationError from None
            await asyncio.to_thread(
                self.repository.publish,
                meeting_id,
                payload,
                details=result.model_dump(mode="json"),
                idempotent=True,
            )
        await asyncio.to_thread(self._progress, transcript_id, "completed")
        return await asyncio.to_thread(self.meetings.result, meeting_id)

    def _progress(self, transcript_id, status):
        from app.audio.models import NormalizedAudio
        from app.speech.repository import TranscriptRecord

        with self.repository.sessions() as session:
            record = session.get(TranscriptRecord, transcript_id)
            audio = session.get(NormalizedAudio, record.source_audio_id)
            # Never overwrite progress belonging to a newer transcription.
            from app.media.models import MediaAsset

            media = session.get(MediaAsset, audio.source_media_id)
            current = latest_transcript(session, media.meeting_id)
            if current is None or current.id != transcript_id:
                return
            media_id = media.id
        self.progress.update(media_id, "analyzing", status)

    async def close(self):
        self.closing = True
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
