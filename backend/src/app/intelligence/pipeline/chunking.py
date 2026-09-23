from app.intelligence.pipeline.errors import AnalysisBudgetError
from app.intelligence.pipeline.models import ExtractionInput, ReviewInput


def payload_bytes(value):
    return len(value.model_dump_json().encode("utf-8"))


def check_budget(value, max_bytes):
    if payload_bytes(value) > max_bytes:
        raise AnalysisBudgetError
    return value


class TranscriptChunker:
    def __init__(self, max_segments, max_bytes, overlap):
        self.max_segments, self.max_bytes, self.overlap = max_segments, max_bytes, overlap

    def chunk(self, transcript, participants=None, speaker_mapping=None):
        def make(targets, context):
            speakers = {s.speaker_id for s in [*targets, *context]}
            return ExtractionInput(
                targets=targets,
                context_only=context,
                participants=participants or [],
                speaker_mapping=[m for m in (speaker_mapping or []) if m.speaker_id in speakers],
            )

        segments, chunks, offset = transcript.segments, [], 0
        while offset < len(segments):
            context = segments[max(0, offset - self.overlap) : offset]
            targets = []
            for segment in segments[offset : offset + self.max_segments]:
                proposed = make([*targets, segment], context)
                if payload_bytes(proposed) > self.max_bytes:
                    if targets:
                        break
                    # Optional context must not prevent an otherwise valid target fitting.
                    while context and payload_bytes(proposed) > self.max_bytes:
                        context = context[1:]
                        proposed = make([segment], context)
                    check_budget(proposed, self.max_bytes)
                targets.append(segment)
            chunks.append(make(targets, context))
            offset += len(targets)
        return chunks


def evidence_for(transcript, ids):
    return [s for s in transcript.segments if s.id in ids]


def review_batches(input, entities, max_bytes):
    """One pass per entity, bounded batches, original global indexes preserved."""
    batches, current = [], []

    def make(items):
        ids = {sid for item in items for sid in item.content.source_segment_ids}
        speakers = {s.speaker_id for s in input.transcript.segments if s.id in ids}
        mappings = [m for m in input.speaker_mapping if m.speaker_id in speakers]
        ids.update(sid for m in mappings for sid in m.evidence_segment_ids)
        return ReviewInput(
            meeting=input.meeting,
            participants=input.participants,
            speaker_mapping=mappings,
            entities=items,
            evidence=evidence_for(input.transcript, ids),
        )

    for entity in entities:
        proposed = make([*current, entity])
        if payload_bytes(proposed) > max_bytes:
            if current:
                batches.append(make(current))
            current = [entity]
            check_budget(make(current), max_bytes)
        else:
            current.append(entity)
    if current:
        batches.append(make(current))
    return batches
