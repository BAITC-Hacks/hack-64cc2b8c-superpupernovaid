import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.canonicalization.models import CanonicalTranscriptSegment
from app.intelligence.pipeline.dependencies import speaker_resolution_profile
from app.intelligence.pipeline.errors import SpeakerResolutionValidationError
from app.intelligence.pipeline.models import (
    Participant,
    SpeakerMapping,
    SpeakerResolutionResult,
    SpeakerResolutionStatus,
)
from app.intelligence.pipeline.speaker_context import SpeakerResolutionContextBuilder
from app.intelligence.pipeline.speaker_repository import (
    SpeakerMappingRecord,
    SpeakerMappingRepository,
)
from app.intelligence.pipeline.speaker_resolution import SpeakerResolutionService


def rows(texts):
    return [
        CanonicalTranscriptSegment(
            id=f"seg_{10 + i}",
            start=i * 5,
            end=i * 5 + 4,
            speaker_id=speaker,
            original_text=text,
            canonical_text=text,
        )
        for i, (speaker, text) in enumerate(texts)
    ]


@pytest.fixture
def speaker_input(meeting_input):
    meeting_input.participants = [
        Participant(id="p3", name="Жандос Талгатович", role="директор департамента инвестиций"),
        Participant(id="p5", name="Салтанат"),
        Participant(id="p6", name="Ерлан"),
    ]
    meeting_input.transcript.segments = rows(
        [
            ("SPEAKER_00", "Жандос Талгатович, по инвестициям что у нас?"),
            ("SPEAKER_02", "По инвестпрограмме за сентябрь освоение 68%."),
        ]
    )
    return meeting_input


class ScriptedRunner:
    def __init__(self, mappings):
        self.mappings, self.calls = mappings, []

    async def run(self, stage, context):
        assert stage == "speaker_resolution"
        self.calls.append(context)
        return SpeakerResolutionResult.model_construct(
            mappings=[
                self.mappings.get(context.speaker_id, SpeakerMapping(speaker_id=context.speaker_id))
            ]
        )


def resolved(speaker="SPEAKER_02", participant="p3", evidence=None):
    return SpeakerMapping(
        speaker_id=speaker,
        participant_id=participant,
        status="resolved",
        evidence_segment_ids=evidence or ["seg_10", "seg_11"],
    )


def service_for(runner, settings, engine):
    return SpeakerResolutionService(
        runner, settings, SpeakerMappingRepository(engine), speaker_resolution_profile(settings)
    )


def test_direct_address_role_evidence_persisted_and_source_immutable(
    speaker_input, settings, engine
):
    runner = ScriptedRunner({"SPEAKER_02": resolved()})
    service = service_for(runner, settings, engine)
    before = speaker_input.model_dump_json()
    result = asyncio.run(service.resolve(speaker_input))
    assert speaker_input.model_dump_json() == before
    assert result.mappings[1] == resolved()
    assert result.mappings[0].status == "unresolved"
    context = runner.calls[1]
    assert [s.id for s in context.segments] == ["seg_10", "seg_11"]
    assert context.participants[0].role == "директор департамента инвестиций"
    assert asyncio.run(service.resolve(speaker_input)) == result and len(runner.calls) == 2
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(SpeakerMappingRecord)) == 1


@pytest.mark.parametrize(
    "text", ["У нас есть юрист Ерлан.", "Доклад закончен.", "Меня зовут Неизвестный Человек."]
)
def test_mention_insufficient_unknown_stay_unresolved(speaker_input, settings, engine, text):
    speaker_input.transcript.segments = rows([("SPEAKER_01", text)])
    runner = ScriptedRunner({})  # Fake semantic decision, not a regex mapping.
    result = asyncio.run(service_for(runner, settings, engine).resolve(speaker_input))
    assert result.mappings[0].status == "unresolved"
    assert result.mappings[0].participant_id is None
    assert runner.calls[0].segments[0].original_text == text


def test_conflict_and_split_labels_are_preserved(speaker_input, settings, engine):
    speaker_input.transcript.segments += rows(
        [
            ("SPEAKER_00", "Салтанат, доложите."),
            ("SPEAKER_02", "Докладываю по кадрам."),
            ("SPEAKER_07", "Жандос снова на связи."),
        ]
    )
    # Assign new stable IDs, not duplicate fixture IDs.
    speaker_input.transcript.segments = [
        s.model_copy(update={"id": f"s{i}"})
        for i, s in enumerate(speaker_input.transcript.segments)
    ]
    conflict = SpeakerMapping(
        speaker_id="SPEAKER_02",
        status="conflict",
        candidate_participant_ids=["p3", "p5"],
        evidence_segment_ids=["s0", "s1", "s2", "s3"],
    )
    runner = ScriptedRunner(
        {"SPEAKER_02": conflict, "SPEAKER_07": resolved("SPEAKER_07", evidence=["s4"])}
    )
    result = asyncio.run(service_for(runner, settings, engine).resolve(speaker_input))
    assert result.mappings[1] == conflict
    assert result.mappings[1].participant_id is None
    runner.mappings["SPEAKER_02"] = resolved(evidence=["s0", "s1"])
    # Change input version so a previously persisted conflict is not reused.
    speaker_input.participants[0].role = "Уточнённая роль"
    result = asyncio.run(service_for(runner, settings, engine).resolve(speaker_input))
    assert [m.participant_id for m in result.mappings[1:]] == ["p3", "p3"]


@pytest.mark.parametrize(
    "updates",
    [
        {"participant_id": "invented"},
        {"speaker_id": "SPEAKER_99"},
        {"evidence_segment_ids": ["missing"]},
        {"evidence_segment_ids": []},
        {"status": SpeakerResolutionStatus.UNRESOLVED},
        {
            "status": SpeakerResolutionStatus.CONFLICT,
            "participant_id": None,
            "candidate_participant_ids": ["p3", "invented"],
        },
        {"evidence_segment_ids": ["seg_10"]},  # Only the chair, not the speaker.
    ],
)
def test_invalid_output_rejected(speaker_input, settings, engine, updates):
    invalid = resolved().model_copy(update=updates)
    runner = ScriptedRunner({"SPEAKER_02": invalid})
    with pytest.raises(SpeakerResolutionValidationError):
        asyncio.run(service_for(runner, settings, engine).resolve(speaker_input))
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(SpeakerMappingRecord)) == 0


@pytest.mark.parametrize("kind", ["duplicate", "missing"])
def test_exact_mapping_coverage(speaker_input, settings, engine, kind):
    async def run(stage, context):
        return SpeakerResolutionResult(
            mappings=[]
            if kind == "missing"
            else [
                SpeakerMapping(speaker_id=context.speaker_id),
                SpeakerMapping(speaker_id=context.speaker_id),
            ]
        )

    with pytest.raises(SpeakerResolutionValidationError):
        asyncio.run(service_for(SimpleNamespace(run=run), settings, engine).resolve(speaker_input))


def test_manual_override_is_versioned_and_bypasses_only_one_speaker(
    speaker_input, settings, engine
):
    runner = ScriptedRunner({})
    service = service_for(runner, settings, engine)
    first = asyncio.run(service.resolve(speaker_input))
    assert first.mappings[1].participant_id is None
    runner.calls.clear()
    speaker_input.speaker_mapping = [resolved()]
    result = asyncio.run(service.resolve(speaker_input))
    assert result.mappings[1].participant_id == "p3"
    assert result.manual_override_speakers == ["SPEAKER_02"]
    assert [c.speaker_id for c in runner.calls] == ["SPEAKER_00"]
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(SpeakerMappingRecord)) == 2


def test_no_participants_or_unknown_never_invent_identity(speaker_input, settings, engine):
    runner = ScriptedRunner({})
    speaker_input.participants = []
    result = asyncio.run(service_for(runner, settings, engine).resolve(speaker_input))
    assert all(m.status == "unresolved" for m in result.mappings) and not runner.calls
    speaker_input.transcript.segments = rows([("UNKNOWN", "Меня зовут Жандос.")])
    speaker_input.participants = [Participant(id="p3", name="Жандос")]
    result = asyncio.run(service_for(runner, settings, engine).resolve(speaker_input))
    assert result.mappings[0].status == "unresolved" and not runner.calls


def test_long_context_keeps_early_and_late_address_windows(speaker_input):
    text = [("SPEAKER_02", "Техническое обсуждение без имени.") for _ in range(200)]
    text[10:12] = [
        ("SPEAKER_00", "Жандос Талгатович, докладывайте."),
        ("SPEAKER_02", "По инвестициям всё готово."),
    ]
    text[180:182] = [
        ("SPEAKER_00", "Салтанат, докладывайте."),
        ("SPEAKER_02", "По кадрам всё готово."),
    ]
    speaker_input.transcript.segments = rows(text)
    context = SpeakerResolutionContextBuilder(35, 30000).build(
        speaker_input.transcript, speaker_input.participants, "SPEAKER_02"
    )
    ids = {s.id for s in context.segments}
    assert {"seg_20", "seg_21", "seg_190", "seg_191"} <= ids
    assert context.context_truncated and len(context.segments) <= 35
    assert context == SpeakerResolutionContextBuilder(35, 30000).build(
        speaker_input.transcript, speaker_input.participants, "SPEAKER_02"
    )


def test_evidence_must_be_in_selected_context(speaker_input, settings, engine):
    speaker_input.transcript.segments = rows([("SPEAKER_02", "Реплика") for _ in range(100)])
    settings.speaker_resolution_max_context_segments = 7
    service = service_for(ScriptedRunner({}), settings, engine)
    context = service.builder.build(
        speaker_input.transcript, speaker_input.participants, "SPEAKER_02"
    )
    absent = next(
        s.id
        for s in speaker_input.transcript.segments
        if s.id not in {c.id for c in context.segments}
    )
    service.runner = ScriptedRunner({"SPEAKER_02": resolved(evidence=[absent])})
    with pytest.raises(SpeakerResolutionValidationError):
        asyncio.run(service.resolve(speaker_input))
