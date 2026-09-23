import asyncio
import hashlib
import logging
from threading import BoundedSemaphore
from uuid import uuid4

from pydantic import ValidationError

from app.intelligence.pipeline.agents import SPECS
from app.intelligence.pipeline.chunking import (
    TranscriptChunker,
    check_budget,
    evidence_for,
    review_batches,
)
from app.intelligence.pipeline.errors import (
    AgentOutputValidationError,
    AnalysisBusyError,
    MeetingIntelligenceError,
)
from app.intelligence.pipeline.models import (
    ActionItem,
    MeetingAnalysis,
    MeetingIntelligenceInput,
    ResolverInput,
    ReviewEntity,
    SummaryInput,
)
from app.intelligence.pipeline.validation import (
    chunk_facts,
    validate_extraction,
    validate_resolved,
    validate_review,
    validate_summary,
)

logger = logging.getLogger(__name__)


class MeetingIntelligenceService:
    def __init__(self, runner, settings, repository, profile_hash, speaker_resolution):
        self.runner, self.settings = runner, settings
        self.speaker_resolution = speaker_resolution
        self.repository, self.profile_hash = repository, profile_hash
        self.chunker = TranscriptChunker(
            settings.meeting_chunk_max_segments,
            settings.meeting_chunk_max_bytes,
            settings.meeting_chunk_overlap_segments,
        )
        self.capacity = BoundedSemaphore(1)
        self.tasks = set()
        self.closing = False

    async def analyze(self, input: MeetingIntelligenceInput) -> MeetingAnalysis:
        if self.closing or not self.capacity.acquire(blocking=False):
            raise AnalysisBusyError
        try:
            snapshot = MeetingIntelligenceInput.model_validate(input.model_dump())
            task = asyncio.create_task(self._run(snapshot))
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

    async def _call(self, stage, payload):
        check_budget(payload, self.settings.meeting_agent_max_input_bytes)
        result = await self.runner.run(stage, payload)
        try:
            # Validate again at the boundary, including injected runners and mutated objects.
            if not isinstance(result, SPECS[stage][1]):
                raise AgentOutputValidationError
            return SPECS[stage][1].model_validate(result.model_dump())
        except ValidationError as exc:
            raise AgentOutputValidationError from exc

    async def _extract(self, batches):
        results = [None] * len(batches)
        pending = iter(enumerate(batches))

        async def worker():
            for index, batch in pending:
                result = await self._call("extraction", batch)
                validate_extraction(result, batch)
                results[index] = result

        async with asyncio.TaskGroup() as group:
            for _ in range(min(self.settings.agent_max_concurrency, len(batches))):
                group.create_task(worker())
        return results

    async def _pipeline(self, input):
        artifact = await self.speaker_resolution.resolve(input)
        input = input.model_copy(update={"speaker_mapping": artifact.mappings})
        if not input.transcript.segments:
            return MeetingAnalysis(
                meeting_id=input.meeting.meeting_id,
                summary="",
                topics=[],
                key_points=[],
                decisions=[],
                action_items=[],
                unresolved_questions=[],
            )
        chunks = await self._extract(
            self.chunker.chunk(input.transcript, input.participants, input.speaker_mapping)
        )
        ids = {
            sid
            for chunk in chunks
            for fact in chunk_facts(chunk)
            for sid in fact.source_segment_ids
        }
        ids.update(sid for mapping in artifact.mappings for sid in mapping.evidence_segment_ids)
        evidence = evidence_for(input.transcript, ids)
        resolved = await self._call(
            "resolver",
            ResolverInput(
                meeting=input.meeting,
                participants=input.participants,
                speaker_mapping=input.speaker_mapping,
                chunks=chunks,
                evidence=evidence,
            ),
        )
        validate_resolved(resolved, input, ids)
        summary = await self._call(
            "summary",
            SummaryInput(
                meeting=input.meeting,
                resolved=resolved,
                chunks=chunks,
                evidence=evidence,
            ),
        )
        validate_summary(summary, ids)
        # Stable positional references within this persisted analysis. Model never assigns UUIDs.
        questions = [*resolved.unresolved_items, *summary.unresolved_questions]
        groups = {
            "action_item": resolved.action_items,
            "decision": resolved.decisions,
            "summary": summary.claims,
            "topic": summary.topics,
            "key_point": summary.key_points,
            "question": questions,
        }
        entities = [
            ReviewEntity(entity_type=kind, entity_index=i, content=item)
            for kind, items in groups.items()
            for i, item in enumerate(items)
        ]
        issues = []
        # Build all batches first so an oversize entity cannot silently skip review.
        for batch in review_batches(input, entities, self.settings.meeting_agent_max_input_bytes):
            review = await self._call("review", batch)
            validate_review(review, batch)
            issues.extend(review.issues)
        flagged = {i.entity_index for i in issues if i.entity_type == "action_item"}
        actions = [
            ActionItem(
                id=uuid4(),
                **a.model_dump(exclude={"deadline_kind", "needs_review"}),
                needs_review=a.needs_review or index in flagged,
            )
            for index, a in enumerate(resolved.action_items)
        ]
        return MeetingAnalysis(
            meeting_id=input.meeting.meeting_id,
            summary=" ".join(c.text for c in summary.claims),
            summary_claims=summary.claims,
            topics=[x.text for x in summary.topics],
            key_points=[x.text for x in summary.key_points],
            decisions=resolved.decisions,
            action_items=actions,
            unresolved_questions=[q.text for q in questions],
            review_required=bool(
                issues
                or questions
                or any(a.needs_review for a in actions)
                or artifact.context_limited_speakers
                or any(m.status != "resolved" for m in artifact.mappings)
            ),
            speaker_mapping=artifact,
            review_issues=issues,
        )

    async def _run(self, input):
        try:
            source_hash = hashlib.sha256(input.model_dump_json().encode()).hexdigest()
            cached = await asyncio.to_thread(
                self.repository.find,
                input.meeting.meeting_id,
                input.transcript.source_audio_id,
                source_hash,
                self.profile_hash,
            )
            if cached is not None:
                self._validate_final(cached, input)
                return cached
            with self.runner.workflow(str(input.meeting.meeting_id)):
                try:
                    result = await self._pipeline(input)
                except ExceptionGroup as exc:
                    # TaskGroup cancels all sibling workers; expose only controlled errors.
                    leaf = exc
                    while isinstance(leaf, BaseExceptionGroup):
                        leaf = leaf.exceptions[0]
                    if isinstance(leaf, MeetingIntelligenceError):
                        raise leaf from None
                    raise MeetingIntelligenceError from None
            self._validate_final(result, input)
            saved = await asyncio.to_thread(
                self.repository.add_or_get,
                result,
                input.transcript.source_audio_id,
                source_hash,
                self.profile_hash,
            )
            self._validate_final(saved, input)
            logger.info(
                "meeting_analysis_done meeting_id=%s actions=%s issues=%s",
                input.meeting.meeting_id,
                len(saved.action_items),
                len(saved.review_issues),
            )
            return saved
        except MeetingIntelligenceError:
            raise
        except Exception as exc:
            raise MeetingIntelligenceError from exc
        finally:
            self.capacity.release()

    @staticmethod
    def _validate_final(result, input):
        from app.intelligence.pipeline.validation import sources

        if result.meeting_id != input.meeting.meeting_id:
            raise AgentOutputValidationError
        from app.intelligence.pipeline.speaker_resolution import validate_mappings

        validate_mappings(
            result.speaker_mapping.mappings,
            input.transcript.segments,
            input.participants,
            {s.speaker_id for s in input.transcript.segments},
        )
        ids = {s.id for s in input.transcript.segments}
        participants = {p.id for p in input.participants}
        for fact in [
            *result.action_items,
            *result.decisions,
            *result.summary_claims,
            *result.review_issues,
        ]:
            sources(fact, ids)
        if len({a.id for a in result.action_items}) != len(result.action_items):
            raise AgentOutputValidationError
        if any(
            a.assignee_participant_id not in participants
            for a in result.action_items
            if a.assignee_participant_id is not None
        ):
            raise AgentOutputValidationError

    async def close(self):
        self.closing = True
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await self.runner.close()
