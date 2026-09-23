import asyncio
import hashlib
import logging
import time
from threading import BoundedSemaphore

from app.canonicalization.batching import make_batches
from app.canonicalization.errors import (
    CanonicalizationBusyError,
    CanonicalizationValidationError,
    TranscriptCanonicalizationError,
)
from app.canonicalization.models import (
    CanonicalizationBatchResult,
    CanonicalTranscript,
    CanonicalTranscriptSegment,
)
from app.speech.models import AttributedTranscript

logger = logging.getLogger(__name__)


def validate_batch(batch, output):
    if not isinstance(output, CanonicalizationBatchResult):
        raise CanonicalizationValidationError
    expected = {s.id for s in batch.targets}
    actual = [s.id for s in output.segments]
    if (
        len(actual) != len(batch.targets)
        or len(set(actual)) != len(actual)
        or set(actual) != expected
    ):
        raise CanonicalizationValidationError
    return {s.id: s for s in output.segments}


def validate_metadata(original, result, language):
    if (
        result.source_audio_id != original.source_audio_id
        or result.canonical_language != language
        or len(result.segments) != len(original.segments)
    ):
        raise CanonicalizationValidationError
    for source, target in zip(original.segments, result.segments, strict=True):
        if (source.id, source.start, source.end, source.speaker_id, source.text) != (
            target.id,
            target.start,
            target.end,
            target.speaker_id,
            target.original_text,
        ) or not target.canonical_text.strip():
            raise CanonicalizationValidationError


class TranscriptCanonicalizationService:
    def __init__(self, canonicalizer, settings, repository, profile_hash):
        self.canonicalizer, self.settings = canonicalizer, settings
        self.repository, self.profile_hash = repository, profile_hash
        # Process-wide cached service: one transcript with at most N in-flight API calls.
        self.capacity = BoundedSemaphore(1)
        self.tasks: set[asyncio.Task] = set()
        self.closing = False

    async def canonicalize(self, transcript: AttributedTranscript) -> CanonicalTranscript:
        if self.closing or not self.capacity.acquire(blocking=False):
            raise CanonicalizationBusyError
        # Preserve a stable snapshot across awaits without modifying Speech's original.
        try:
            original = transcript.model_copy(deep=True)
            task = asyncio.create_task(self._run(original))
        except BaseException:
            self.capacity.release()
            raise
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _run(self, original):
        started = time.monotonic()
        try:
            source_hash = hashlib.sha256(original.model_dump_json().encode()).hexdigest()
            s = self.settings
            cached = await asyncio.to_thread(
                self.repository.find, original.source_audio_id, source_hash, self.profile_hash
            )
            if cached is not None:
                validate_metadata(original, cached, s.transcript_canonical_language)
                return cached
            batches = make_batches(
                original,
                language=s.transcript_canonical_language,
                max_segments=s.canonicalization_batch_max_segments,
                max_bytes=s.canonicalization_batch_max_bytes,
                context_segments=s.canonicalization_context_segments,
            )
            results = [None] * len(batches)
            pending = iter(enumerate(batches))

            async def worker():
                for index, batch in pending:
                    result = await self.canonicalizer.canonicalize_batch(batch)
                    results[index] = validate_batch(batch, result)

            # Fixed workers: no task per segment/batch and no unbounded waiting queue.
            workers = [
                asyncio.create_task(worker())
                for _ in range(min(s.canonicalization_max_concurrency, len(batches)))
            ]
            try:
                await asyncio.gather(*workers)
            except BaseException:
                for task in workers:
                    task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                raise
            segments = []
            for batch, mapping in zip(batches, results, strict=True):
                for source in batch.targets:
                    output = mapping[source.id]
                    segments.append(
                        CanonicalTranscriptSegment(
                            id=source.id,
                            start=source.start,
                            end=source.end,
                            speaker_id=source.speaker_id,
                            original_text=source.text,
                            canonical_text=output.canonical_text,
                            canonicalization_uncertain=output.uncertain,
                        )
                    )
            result = CanonicalTranscript(
                source_audio_id=original.source_audio_id,
                canonical_language=s.transcript_canonical_language,
                segments=segments,
            )
            validate_metadata(original, result, s.transcript_canonical_language)
            result = await asyncio.to_thread(
                self.repository.add_or_get, result, source_hash, self.profile_hash
            )
            validate_metadata(original, result, s.transcript_canonical_language)
            logger.info(
                "canonicalization_done audio_id=%s segments=%s batches=%s language=%s "
                "elapsed=%.3f uncertain=%s",
                original.source_audio_id,
                len(segments),
                len(batches),
                s.transcript_canonical_language,
                time.monotonic() - started,
                sum(segment.canonicalization_uncertain for segment in result.segments),
            )
            return result
        except TranscriptCanonicalizationError as exc:
            logger.warning(
                "canonicalization_failed audio_id=%s code=%s", original.source_audio_id, exc.code
            )
            raise
        except Exception as exc:
            logger.warning("canonicalization_failed audio_id=%s", original.source_audio_id)
            raise TranscriptCanonicalizationError from exc
        finally:
            self.capacity.release()

    async def close(self):
        self.closing = True
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        close = getattr(self.canonicalizer, "close", None)
        if close is not None:
            await close()
