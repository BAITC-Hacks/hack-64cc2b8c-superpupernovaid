import asyncio
import hashlib
import json
import logging

from pydantic import ValidationError

from app.intelligence.pipeline.errors import (
    SpeakerResolutionError,
    SpeakerResolutionValidationError,
)
from app.intelligence.pipeline.models import (
    MeetingIntelligenceInput,
    SpeakerMapping,
    SpeakerMappingArtifact,
    SpeakerResolutionResult,
    SpeakerResolutionStatus,
)
from app.intelligence.pipeline.speaker_context import SpeakerResolutionContextBuilder

logger = logging.getLogger(__name__)


def validate_mappings(mappings, transcript, participants, expected_speakers):
    speakers = [m.speaker_id for m in mappings]
    if len(speakers) != len(set(speakers)) or set(speakers) != set(expected_speakers):
        raise SpeakerResolutionValidationError
    segment_map = {s.id: s for s in transcript}
    participant_ids = {p.id for p in participants}
    for original in mappings:
        try:
            mapping = SpeakerMapping.model_validate(original.model_dump())
        except ValidationError as exc:
            raise SpeakerResolutionValidationError from exc
        if (
            mapping.participant_id is not None
            and mapping.participant_id not in participant_ids
            or not set(mapping.candidate_participant_ids) <= participant_ids
            or not set(mapping.evidence_segment_ids) <= set(segment_map)
        ):
            raise SpeakerResolutionValidationError
        if mapping.status != SpeakerResolutionStatus.UNRESOLVED and not any(
            segment_map[sid].speaker_id == mapping.speaker_id
            for sid in mapping.evidence_segment_ids
        ):
            raise SpeakerResolutionValidationError


class SpeakerResolutionService:
    def __init__(self, runner, settings, repository, profile_hash):
        self.runner, self.repository, self.profile_hash = runner, repository, profile_hash
        self.concurrency = settings.agent_max_concurrency
        self.builder = SpeakerResolutionContextBuilder(
            settings.speaker_resolution_max_context_segments,
            settings.meeting_agent_max_input_bytes,
        )

    async def resolve(self, input):
        input = MeetingIntelligenceInput.model_validate(input.model_dump())
        # Canonical metadata is never edited. Human corrections are versioned input artifacts.
        source = {
            "transcript": input.transcript.model_dump(mode="json"),
            "participants": [p.model_dump() for p in input.participants],
            "overrides": [m.model_dump(mode="json") for m in input.speaker_mapping],
        }
        fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        speakers = list(dict.fromkeys(s.speaker_id for s in input.transcript.segments))
        cached = await asyncio.to_thread(
            self.repository.find,
            input.meeting.meeting_id,
            input.transcript.source_audio_id,
            fingerprint,
            self.profile_hash,
        )
        if cached is not None:
            validate_mappings(
                cached.mappings, input.transcript.segments, input.participants, speakers
            )
            return cached
        overrides = {m.speaker_id: m for m in input.speaker_mapping}
        validate_mappings(
            list(overrides.values()), input.transcript.segments, input.participants, overrides
        )
        mappings = {
            speaker: overrides[speaker].model_copy(deep=True)
            if speaker in overrides
            else SpeakerMapping(speaker_id=speaker)
            for speaker in speakers
        }
        contexts = [
            self.builder.build(input.transcript, input.participants, speaker)
            for speaker in speakers
            if input.participants and speaker != "UNKNOWN" and speaker not in overrides
        ]
        pending = iter(contexts)

        async def worker():
            for context in pending:
                result = await self.runner.run("speaker_resolution", context)
                try:
                    if not isinstance(result, SpeakerResolutionResult):
                        raise SpeakerResolutionValidationError
                    result = SpeakerResolutionResult.model_validate(result.model_dump())
                except ValidationError as exc:
                    raise SpeakerResolutionValidationError from exc
                validate_mappings(
                    result.mappings, context.segments, input.participants, [context.speaker_id]
                )
                mappings[context.speaker_id] = result.mappings[0]

        tasks = [asyncio.create_task(worker()) for _ in range(min(self.concurrency, len(contexts)))]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        result = SpeakerMappingArtifact(
            mappings=[mappings[s] for s in speakers],
            context_limited_speakers=[c.speaker_id for c in contexts if c.context_truncated],
            manual_override_speakers=list(overrides),
        )
        validate_mappings(result.mappings, input.transcript.segments, input.participants, speakers)
        try:
            saved = await asyncio.to_thread(
                self.repository.add_or_get,
                result,
                input.meeting.meeting_id,
                input.transcript.source_audio_id,
                fingerprint,
                self.profile_hash,
            )
        except Exception as exc:
            raise SpeakerResolutionError from exc
        validate_mappings(saved.mappings, input.transcript.segments, input.participants, speakers)
        logger.info(
            "speaker_resolution_done meeting_id=%s speakers=%s participants=%s "
            "resolved=%s unresolved=%s conflicts=%s",
            input.meeting.meeting_id,
            len(speakers),
            len(input.participants),
            sum(m.status == "resolved" for m in saved.mappings),
            sum(m.status == "unresolved" for m in saved.mappings),
            sum(m.status == "conflict" for m in saved.mappings),
        )
        return saved
