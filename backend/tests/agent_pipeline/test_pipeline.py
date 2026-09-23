import asyncio
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.intelligence.pipeline.chunking import TranscriptChunker, payload_bytes
from app.intelligence.pipeline.errors import (
    AgentOutputValidationError,
    AnalysisBudgetError,
    AnalysisBusyError,
    ExtractionAgentError,
)
from app.intelligence.pipeline.models import ReviewIssue, ReviewResult, SpeakerMapping
from app.intelligence.pipeline.repository import MeetingAnalysisRecord
from app.intelligence.pipeline.validation import validate_extraction, validate_resolved


def test_end_to_end_cache_and_immutable_input(service, fake, meeting_input):
    before = meeting_input.model_dump_json()
    result = asyncio.run(service.analyze(meeting_input))
    assert meeting_input.model_dump_json() == before
    (action,) = result.action_items
    assert action.task == "Завершить интеграцию" and action.assignee_participant_id == "daniyar"
    assert action.deadline == date(2026, 9, 25)
    assert action.source_segment_ids == ["seg_041", "seg_057"]
    assert result.review_required  # Speaker remains unresolved; explicit assignee is still valid.
    assert fake.peak == 2
    assert [stage for stage, _ in fake.calls] == ["speaker_resolution"] + ["extraction"] * 3 + [
        "resolver",
        "summary",
        "review",
    ]
    resolver = next(p for stage, p in fake.calls if stage == "resolver")
    assert len(resolver.chunks) == 3
    review = fake.calls[-1][1]
    assert [s.id for s in review.evidence] == ["seg_041", "seg_057"]
    count = len(fake.calls)
    assert asyncio.run(service.analyze(meeting_input)) == result
    assert len(fake.calls) == count
    meeting_input.meeting.title = "Updated title"
    assert asyncio.run(service.analyze(meeting_input)).action_items[0].id != action.id


def test_chunker_budgets_and_overlap(meeting_input):
    chunker = TranscriptChunker(1, 1024, 1)
    chunks = chunker.chunk(meeting_input.transcript)
    assert [s.id for c in chunks for s in c.targets] == ["seg_041", "seg_057", "seg_060"]
    assert chunks[1].context_only[0].id == "seg_041"
    assert all(payload_bytes(c) <= 1024 for c in chunks)
    meeting_input.transcript.segments[-1] = meeting_input.transcript.segments[-1].model_copy(
        update={"canonical_text": "я" * 5000}
    )
    with pytest.raises(AnalysisBudgetError):
        chunker.chunk(meeting_input.transcript)


@pytest.mark.parametrize("ids", [["unknown"], [], ["seg_041", "seg_041"], ["seg_060"]])
def test_invalid_extraction_evidence(service, fake, meeting_input, ids):
    original = fake.run

    async def damaged(stage, payload):
        result = await original(stage, payload)
        if stage == "extraction" and result.action_items:
            result.action_items[0].source_segment_ids = ids
        return result

    fake.run = damaged
    with pytest.raises(AgentOutputValidationError):
        asyncio.run(service.analyze(meeting_input))
    assert not any(stage == "resolver" for stage, _ in fake.calls)


def test_overlap_only_fact_rejected(fake, meeting_input):
    batch = TranscriptChunker(1, 2000, 1).chunk(meeting_input.transcript)[1]
    result = asyncio.run(fake.run("extraction", batch))
    result.unresolved_references[0].source_segment_ids = ["seg_041"]
    with pytest.raises(AgentOutputValidationError):
        validate_extraction(result, batch)


@pytest.mark.parametrize("fault", ["participant", "sources", "relative_without_context"])
def test_resolver_validation(service, fake, meeting_input, fault):
    action = fake.resolved.action_items[0]
    if fault == "participant":
        action.assignee_participant_id = "invented"
    elif fault == "sources":
        action.source_segment_ids = ["seg_060"]  # exists but was not sent to resolver
    else:
        meeting_input.meeting.started_at = None
    with pytest.raises(AgentOutputValidationError):
        asyncio.run(service.analyze(meeting_input))


def test_missing_assignee_deadline_mapping_are_allowed(service, fake, meeting_input):
    action = fake.resolved.action_items[0]
    action.assignee_name = action.assignee_participant_id = None
    action.deadline = action.deadline_text = None
    action.deadline_kind = "unspecified"
    meeting_input.speaker_mapping = [SpeakerMapping(speaker_id="SPEAKER_00", participant_id=None)]
    result = asyncio.run(service.analyze(meeting_input))
    assert result.action_items[0].deadline is None
    assert result.action_items[0].needs_review and result.review_required


def test_relative_without_context_stays_null(service, fake, meeting_input):
    meeting_input.meeting.timezone = None
    fake.resolved.action_items[0].deadline = None
    result = asyncio.run(service.analyze(meeting_input))
    assert result.action_items[0].needs_review


def test_review_marks_without_rewriting(service, fake, meeting_input):
    fake.review = ReviewResult(
        approved=False,
        issues=[
            ReviewIssue(
                entity_type="action_item",
                entity_index=0,
                field="deadline",
                reason="Связь неоднозначна",
                source_segment_ids=["seg_057"],
            )
        ],
    )
    result = asyncio.run(service.analyze(meeting_input))
    assert result.review_required and result.action_items[0].needs_review
    assert result.action_items[0].task == fake.resolved.action_items[0].task
    assert result.review_issues == fake.review.issues
    assert sum(s == "resolver" for s, _ in fake.calls) == 1


def test_invalid_review_index(service, fake, meeting_input):
    fake.review = ReviewResult(
        approved=False,
        issues=[
            ReviewIssue(
                entity_type="action_item",
                entity_index=9,
                field=None,
                reason="No proof",
                source_segment_ids=["seg_041"],
            )
        ],
    )
    with pytest.raises(AgentOutputValidationError):
        asyncio.run(service.analyze(meeting_input))


def test_partial_failure_saves_nothing_and_releases_capacity(service, fake, meeting_input, engine):
    original = fake.run

    async def broken(stage, payload):
        if stage == "extraction":
            raise ExtractionAgentError
        return await original(stage, payload)

    fake.run = broken
    with pytest.raises(ExtractionAgentError):
        asyncio.run(service.analyze(meeting_input))
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(MeetingAnalysisRecord)) == 0
    fake.run = original
    assert asyncio.run(service.analyze(meeting_input)).action_items


def test_downstream_budget_no_partial_save(service, fake, meeting_input):
    service.settings.meeting_agent_max_input_bytes = 1024
    with pytest.raises(AnalysisBudgetError):
        asyncio.run(service.analyze(meeting_input))
    assert not any(stage == "resolver" for stage, _ in fake.calls)


def test_empty_transcript_no_calls(service, fake, meeting_input):
    meeting_input.transcript.segments = []
    result = asyncio.run(service.analyze(meeting_input))
    assert not result.action_items and not fake.calls


def test_cancellation_retains_capacity_and_persists(service, fake, meeting_input):
    async def scenario():
        task = asyncio.create_task(service.analyze(meeting_input))
        await asyncio.sleep(0.001)
        with pytest.raises(AnalysisBusyError):
            await service.analyze(meeting_input)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await service.close()
        assert len(fake.calls) == 7

    asyncio.run(scenario())


def test_unknown_mapping_and_bad_timezone(meeting_input):
    data = meeting_input.model_dump()
    data["speaker_mapping"] = [{"speaker_id": "SPEAKER_00", "participant_id": "unknown"}]
    with pytest.raises(ValidationError):
        type(meeting_input).model_validate(data)
    data["speaker_mapping"] = []
    data["meeting"]["timezone"] = "Not/AZone"
    with pytest.raises(ValidationError):
        type(meeting_input).model_validate(data)


def test_duplicate_name_requires_mapping(fake, meeting_input):
    meeting_input.participants.append(
        meeting_input.participants[0].model_copy(update={"id": "other"})
    )
    with pytest.raises(AgentOutputValidationError):
        validate_resolved(fake.resolved, meeting_input, {"seg_041", "seg_057"})


def test_review_batches_keep_global_indexes_and_no_unrelated_evidence(meeting_input):
    from app.intelligence.pipeline.chunking import review_batches
    from app.intelligence.pipeline.models import GroundedText, ReviewEntity

    entities = [
        ReviewEntity(
            entity_type="summary",
            entity_index=i,
            content=GroundedText(
                text="Текст " * 35,
                source_segment_ids=["seg_041"],
            ),
        )
        for i in range(8)
    ]
    batches = review_batches(meeting_input, entities, 1700)
    assert len(batches) > 1
    assert [e.entity_index for b in batches for e in b.entities] == list(range(8))
    assert all([s.id for s in b.evidence] == ["seg_041"] for b in batches)
    assert all(payload_bytes(b) <= 1700 for b in batches)


def test_summary_cannot_replace_actions_or_cite_unseen_evidence(service, fake, meeting_input):
    original = fake.run

    async def damaged(stage, payload):
        result = await original(stage, payload)
        if stage == "summary":
            result.claims[0].source_segment_ids = ["seg_060"]
        return result

    fake.run = damaged
    with pytest.raises(AgentOutputValidationError):
        asyncio.run(service.analyze(meeting_input))


def test_canonicalization_uncertainty_requires_review(service, meeting_input):
    meeting_input.transcript.segments[0] = meeting_input.transcript.segments[0].model_copy(
        update={"canonicalization_uncertain": True}
    )
    result = asyncio.run(service.analyze(meeting_input))
    assert result.action_items[0].needs_review and result.review_required


def test_resolved_mapping_reaches_extraction_and_result_without_changing_speaker(
    service, fake, meeting_input
):
    from app.intelligence.pipeline.models import SpeakerMapping, SpeakerResolutionResult

    original = fake.run
    before = meeting_input.transcript.model_dump_json()

    async def run(stage, payload):
        if stage == "speaker_resolution":
            fake.calls.append((stage, payload))
            return SpeakerResolutionResult(
                mappings=[
                    SpeakerMapping(
                        speaker_id="SPEAKER_00",
                        participant_id="daniyar",
                        status="resolved",
                        evidence_segment_ids=["seg_041"],
                    )
                ]
            )
        if stage == "extraction":
            assert payload.speaker_mapping[0].participant_id == "daniyar"
            assert payload.participants[0].name == "Данияр"
            assert payload.targets[0].speaker_id == "SPEAKER_00"
        return await original(stage, payload)

    fake.run = run
    result = asyncio.run(service.analyze(meeting_input))
    assert result.speaker_mapping.mappings[0].participant_id == "daniyar"
    assert meeting_input.transcript.model_dump_json() == before
