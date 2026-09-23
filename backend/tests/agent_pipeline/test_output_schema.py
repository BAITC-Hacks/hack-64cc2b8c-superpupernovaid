import jsonschema
import pytest

from app.intelligence.pipeline.chunking import TranscriptChunker
from app.intelligence.pipeline.errors import AgentOutputValidationError
from app.intelligence.pipeline.models import ChunkAnalysis
from app.intelligence.pipeline.output_schema import EvidenceOutputSchema
from app.intelligence.pipeline.validation import target_findings, validate_extraction


def test_only_supplied_evidence_and_participants_are_allowed(meeting_input):
    batch = TranscriptChunker(1, 10000, 0).chunk(meeting_input.transcript)[0]
    schema = EvidenceOutputSchema(ChunkAnalysis, batch).json_schema()
    result = {
        "action_items": [],
        "decisions": [],
        "unresolved_references": [],
        "important_facts": [{"text": "Факт", "source_segment_ids": [batch.targets[0].id]}],
    }
    jsonschema.validate(result, schema)
    result["important_facts"][0]["source_segment_ids"] = ["invented-id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, schema)


def test_empty_participants_only_allow_null_assignee(meeting_input):
    batch = TranscriptChunker(1, 10000, 0).chunk(meeting_input.transcript)[0]
    schema = EvidenceOutputSchema(ChunkAnalysis, batch).json_schema()
    assert schema["$defs"]["CandidateActionItem"]["properties"]["assignee_participant_id"] == {
        "type": "null"
    }


def test_request_schemas_do_not_leak_between_chunks(meeting_input):
    batches = TranscriptChunker(1, 10000, 0).chunk(meeting_input.transcript)
    first = EvidenceOutputSchema(ChunkAnalysis, batches[0])
    second = EvidenceOutputSchema(ChunkAnalysis, batches[1])
    assert first.json_schema()["$defs"]["SuppliedEvidenceId"]["enum"] == [batches[0].targets[0].id]
    assert second.json_schema()["$defs"]["SuppliedEvidenceId"]["enum"] == [batches[1].targets[0].id]
    schema = first.json_schema()
    schema["$defs"]["SuppliedEvidenceId"]["enum"].append("injected")
    assert "injected" not in first.json_schema()["$defs"]["SuppliedEvidenceId"]["enum"]


def test_context_only_evidence_is_still_rejected(meeting_input):
    batch = TranscriptChunker(1, 10000, 1).chunk(meeting_input.transcript)[1]
    result = ChunkAnalysis(
        action_items=[],
        decisions=[],
        unresolved_references=[],
        important_facts=[
            {"text": "Факт", "source_segment_ids": [batch.context_only[0].id]},
        ],
    )
    jsonschema.validate(
        result.model_dump(mode="json"), EvidenceOutputSchema(ChunkAnalysis, batch).json_schema()
    )
    with pytest.raises(AgentOutputValidationError) as exc:
        validate_extraction(result, batch)
    assert exc.value.reason == "no_target_evidence"


def test_overlap_filter_preserves_cross_chunk_evidence_and_rejects_unknown_ids(meeting_input):
    batch = TranscriptChunker(1, 10000, 1).chunk(meeting_input.transcript)[1]
    target, context = batch.targets[0].id, batch.context_only[0].id
    result = ChunkAnalysis(action_items=[], decisions=[], unresolved_references=[],
        important_facts=[
            {"text": "Earlier", "source_segment_ids": [context]},
            {"text": "Clarification", "source_segment_ids": [context, target]},
            {"text": "Current", "source_segment_ids": [target]},
        ])
    filtered = target_findings(result, batch)
    validate_extraction(filtered, batch)
    assert [f.text for f in filtered.important_facts] == ["Clarification", "Current"]
    assert filtered.important_facts[0].source_segment_ids == [context, target]
    assert len(result.important_facts) == 3
    result.important_facts[0].source_segment_ids = [context, "invented-id"]
    with pytest.raises(AgentOutputValidationError) as exc:
        target_findings(result, batch)
    assert exc.value.reason == "unknown_sources"
