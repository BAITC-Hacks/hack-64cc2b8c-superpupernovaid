import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException

from app.processing.errors import MeetingProcessingError, ProcessingQueueError
from app.processing.repository import ProcessingRepository

logger = logging.getLogger(__name__)


class SubmitMeetingProcessing:
    def __init__(self, repository, queue, preflight):
        self.repository, self.queue, self.preflight = repository, queue, preflight

    def submit(self, meeting_id, payload):
        self.preflight(meeting_id, payload.media_id)
        run, created = self.repository.submit(meeting_id, payload)
        if created or run.status == "queued":
            # Redelivery also repairs a crash between DB reservation and broker publish.
            try:
                self.queue.enqueue(run.id)
            except Exception:
                # A publish timeout may happen after delivery: never overwrite running/completed.
                self.repository.fail(
                    run.id,
                    ProcessingQueueError.code,
                    ProcessingQueueError.message,
                    only_queued=True,
                )
                raise ProcessingQueueError from None
        return run


class MeetingProcessingService:
    def __init__(self, repository: ProcessingRepository, stages):
        self.repository, self.stages = repository, stages

    async def execute(self, run_id: UUID):
        run = await asyncio.to_thread(self.repository.claim, run_id)
        if run is None:
            return  # Duplicate or outdated delivery.
        try:
            await self.stages.validate(run)
            audio = await self._stage(run, "preprocessing", lambda: self.stages.preprocess(run))
            # SpeechService reports the actual ASR/diarization boundaries through its tracker.
            transcript = await self._stage(
                run, "transcribing", lambda: self.stages.speech(run, audio)
            )
            await asyncio.to_thread(self.repository.transition, run.id, "diarizing", "completed")
            await self._stage(
                run, "canonicalizing", lambda: self.stages.canonicalize(run, transcript)
            )
            await self._stage(run, "resolving_speakers", lambda: self.stages.speakers(run))
            await self._stage(run, "analyzing", lambda: self.stages.analyze(run))
            exports = await self._stage(run, "exporting", lambda: self.stages.export(run))
            await asyncio.to_thread(self.repository.finish, run.id, exports)
            logger.info(
                "meeting_processing_completed run_id=%s meeting_id=%s", run.id, run.meeting_id
            )
        except Exception as exc:
            # Only expose declared application errors; arbitrary exception text can contain secrets.
            from app.audio.errors import AudioProcessingError
            from app.canonicalization.errors import TranscriptCanonicalizationError
            from app.intelligence.pipeline.errors import MeetingIntelligenceError
            from app.media.errors import MediaError
            from app.protocols.errors import ProtocolExportError
            from app.speech.errors import SpeechProcessingError

            safe = (
                MeetingProcessingError,
                MeetingIntelligenceError,
                AudioProcessingError,
                TranscriptCanonicalizationError,
                MediaError,
                ProtocolExportError,
                SpeechProcessingError,
            )
            code, message = MeetingProcessingError.code, MeetingProcessingError.message
            if isinstance(exc, safe):
                code, message = exc.code, exc.message
            elif isinstance(exc, HTTPException) and exc.status_code == 409:
                code, message = (
                    "processing_prerequisite_changed",
                    "Meeting inputs changed or prerequisites are missing",
                )
            await asyncio.to_thread(self.repository.fail, run.id, code, message)
            logger.warning("meeting_processing_failed run_id=%s code=%s", run.id, code)

    async def _stage(self, run, name: str, operation: Callable[[], Awaitable]):
        await asyncio.to_thread(self.repository.transition, run.id, name, "running")
        result = await operation()
        await asyncio.to_thread(self.repository.transition, run.id, name, "completed")
        return result
