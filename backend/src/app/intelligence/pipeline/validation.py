from app.intelligence.pipeline.errors import AgentOutputValidationError


def sources(value, allowed, targets=None):
    ids = value.source_segment_ids
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= allowed:
        raise AgentOutputValidationError
    if targets is not None and not set(ids) & targets:
        raise AgentOutputValidationError


def chunk_facts(chunk):
    return [
        *chunk.action_items,
        *chunk.decisions,
        *chunk.important_facts,
        *chunk.unresolved_references,
    ]


def validate_extraction(result, batch):
    targets = {s.id for s in batch.targets}
    allowed = targets | {s.id for s in batch.context_only}
    for fact in chunk_facts(result):
        sources(fact, allowed, targets)
    participants = {p.id for p in batch.participants}
    if any(
        a.assignee_participant_id not in participants
        for a in result.action_items
        if a.assignee_participant_id is not None
    ):
        raise AgentOutputValidationError


def validate_resolved(result, input, allowed):
    participants = {p.id: p.name for p in input.participants}
    for fact in [*result.action_items, *result.decisions, *result.unresolved_items]:
        sources(fact, allowed)
    for action in result.action_items:
        pid = action.assignee_participant_id
        if pid is not None:
            if pid not in participants or action.assignee_name != participants[pid]:
                raise AgentOutputValidationError
            duplicates = sum(
                p.name.casefold() == participants[pid].casefold() for p in input.participants
            )
            mapped = {
                m.participant_id
                for m in input.speaker_mapping
                if m.speaker_id
                in {
                    s.speaker_id
                    for s in input.transcript.segments
                    if s.id in action.source_segment_ids
                }
            }
            if duplicates > 1 and pid not in mapped:
                raise AgentOutputValidationError
        else:
            action.needs_review = True
        if action.deadline_kind == "unspecified":
            if action.deadline is not None or action.deadline_text is not None:
                raise AgentOutputValidationError
        elif action.deadline_text is None:
            raise AgentOutputValidationError
        if action.deadline_text is not None:
            evidence = [s for s in input.transcript.segments if s.id in action.source_segment_ids]
            phrase = " ".join(action.deadline_text.split())
            originals = " ".join(" ".join(s.original_text.split()) for s in evidence)
            canonical = " ".join(" ".join(s.canonical_text.split()) for s in evidence)
            if phrase not in originals and phrase not in canonical:
                raise AgentOutputValidationError
        if action.deadline_kind == "relative" and (
            input.meeting.started_at is None or input.meeting.timezone is None
        ):
            if action.deadline is not None:
                raise AgentOutputValidationError
            action.needs_review = True
        if action.deadline_text is not None and action.deadline is None:
            action.needs_review = True
        if any(
            s.canonicalization_uncertain
            for s in input.transcript.segments
            if s.id in action.source_segment_ids
        ):
            action.needs_review = True


def validate_summary(result, allowed):
    for fact in [*result.claims, *result.topics, *result.key_points, *result.unresolved_questions]:
        sources(fact, allowed)


def validate_review(result, batch):
    entities = {(e.entity_type, e.entity_index): e for e in batch.entities}
    for issue in result.issues:
        entity = entities.get((issue.entity_type, issue.entity_index))
        if entity is None:
            raise AgentOutputValidationError
        allowed = set(entity.content.source_segment_ids)
        speakers = {s.speaker_id for s in batch.evidence if s.id in allowed}
        allowed.update(
            sid
            for mapping in batch.speaker_mapping
            if mapping.speaker_id in speakers
            for sid in mapping.evidence_segment_ids
        )
        sources(issue, allowed)
