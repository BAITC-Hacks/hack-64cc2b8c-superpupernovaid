import asyncio
import logging
import time
from threading import BoundedSemaphore

from app.audio.models import NormalizedAudio
from app.speech.alignment import SpeakerTranscriptAligner
from app.speech.errors import SpeechAlignmentError, SpeechBusyError, SpeechProcessingError
from app.speech.interfaces import SpeakerDiarizer, SpeechRecognizer
from app.speech.models import AttributedTranscript
from app.speech.repository import SpeechRepository

logger = logging.getLogger(__name__)


class SpeechService:
    def __init__(
        self,
        recognizer: SpeechRecognizer,
        diarizer: SpeakerDiarizer,
        aligner: SpeakerTranscriptAligner,
        repository: SpeechRepository,
        profile_hash: str,
        validate_audio=None,
        tracker=None,
    ):
        self.recognizer, self.diarizer, self.aligner = recognizer, diarizer, aligner
        self.repository, self.profile_hash = repository, profile_hash
        self.validate_audio = validate_audio
        self.tracker = tracker
        # One active pipeline per process, including model initialization. No waiting queue.
        self.capacity = BoundedSemaphore(1)
        self.tasks: set[asyncio.Task] = set()
        self.closing = False

    async def process(self, audio: NormalizedAudio) -> AttributedTranscript:
        if self.closing or not self.capacity.acquire(blocking=False):
            raise SpeechBusyError
        task = asyncio.create_task(self._run(audio))
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        # Disconnect/cancellation must not release capacity while GPU/thread work still runs.
        return await asyncio.shield(task)

    def _finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()  # Retrieve exceptions even when the HTTP caller disconnected.

    async def _run(self, audio):
        start = time.monotonic()
        stage = "transcribing"
        try:
            cached = await asyncio.to_thread(self.repository.find, audio.id, self.profile_hash)
            if cached is not None:
                if self.tracker:
                    for completed_stage in ("transcribing", "diarizing"):
                        await asyncio.to_thread(
                            self.tracker.speech, audio, completed_stage, "completed"
                        )
                return cached
            if self.validate_audio is not None:
                self.validate_audio(audio)
            if self.tracker:
                await asyncio.to_thread(self.tracker.speech, audio, stage, "running")
            transcription = await self.recognizer.transcribe(audio)
            if self.tracker:
                await asyncio.to_thread(self.tracker.speech, audio, stage, "completed")
            stage = "diarizing"
            if self.tracker:
                await asyncio.to_thread(self.tracker.speech, audio, stage, "running")
            diarization = await self.diarizer.diarize(audio)
            if any(
                s.end > audio.duration_seconds + 0.1
                for s in (*transcription.segments, *diarization.segments)
            ):
                raise SpeechAlignmentError
            try:
                result = await asyncio.to_thread(
                    self.aligner.align, transcription, diarization, source_audio_id=audio.id
                )
            except Exception as exc:
                raise SpeechAlignmentError from exc
            result = await asyncio.to_thread(self.repository.add_or_get, result, self.profile_hash)
            if self.tracker:
                await asyncio.to_thread(self.tracker.speech, audio, stage, "completed")
            logger.info(
                "speech_done audio_id=%s elapsed=%.3f segments=%s speakers=%s",
                audio.id,
                time.monotonic() - start,
                len(result.segments),
                len({s.speaker_id for s in result.segments} - {"UNKNOWN"}),
            )
            return result
        except SpeechProcessingError as exc:
            if self.tracker:
                await asyncio.to_thread(self.tracker.speech, audio, stage, "failed")
            logger.warning("speech_failed audio_id=%s code=%s", audio.id, exc.code)
            raise
        except Exception as exc:
            if self.tracker:
                await asyncio.to_thread(self.tracker.speech, audio, stage, "failed")
            logger.warning("speech_failed audio_id=%s code=speech_processing_failed", audio.id)
            raise SpeechProcessingError from exc
        finally:
            self.capacity.release()

    async def close(self):
        self.closing = True
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        for adapter in (self.recognizer, self.diarizer):
            close = getattr(adapter, "close", None)
            if close is not None:
                await asyncio.to_thread(close)
