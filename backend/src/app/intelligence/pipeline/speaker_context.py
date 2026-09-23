import re

from app.intelligence.pipeline.chunking import payload_bytes
from app.intelligence.pipeline.errors import AnalysisBudgetError
from app.intelligence.pipeline.models import SpeakerResolutionContext


def spread(values):
    """Prioritize both ends, then bisect; do not consume the budget on the meeting's start."""
    if not values:
        return []
    result, ranges = [], [(0, len(values) - 1)]
    seen = set()
    while ranges:
        low, high = ranges.pop(0)
        for index in (low, high, (low + high) // 2):
            if index not in seen:
                seen.add(index)
                result.append(values[index])
        mid = (low + high) // 2
        if low + 1 <= mid - 1:
            ranges.append((low + 1, mid - 1))
        if mid + 1 <= high - 1:
            ranges.append((mid + 1, high - 1))
    return result


class SpeakerResolutionContextBuilder:
    """Select evidence, never decide identity. Every sample keeps its original stable metadata."""

    def __init__(self, max_segments, max_bytes):
        self.max_segments, self.max_bytes = max_segments, max_bytes

    def build(self, transcript, participants, speaker_id):
        segments = transcript.segments
        own = [i for i, s in enumerate(segments) if s.speaker_id == speaker_id]
        if not own:
            raise AnalysisBudgetError
        names = {
            word.casefold()
            for p in participants
            for word in re.findall(r"\w+", p.name)
            if len(word) >= 3
        }
        # Name hits only select nearby evidence. They NEVER create an identity mapping.
        addressed = [
            i
            for i, s in enumerate(segments)
            if names
            & {w.casefold() for w in re.findall(r"\w+", s.original_text + " " + s.canonical_text)}
            and any(
                segments[j].speaker_id == speaker_id
                for j in range(max(0, i - 3), min(len(segments), i + 4))
            )
        ]
        longest = sorted(own, key=lambda i: (-len(segments[i].canonical_text), i))[:3]
        transitions = [i for i in own if i == 0 or segments[i - 1].speaker_id != speaker_id]
        order = list(
            dict.fromkeys(
                [own[0], *spread(addressed), own[-1], *longest, *spread(transitions), *spread(own)]
            )
        )
        selected = set()

        def payload(indices):
            return SpeakerResolutionContext(
                speaker_id=speaker_id,
                participants=participants,
                segments=[segments[i] for i in sorted(indices)],
                context_truncated=len(indices) < len(segments),
            )

        # When small, use the whole meeting; otherwise retain intact neighboring windows.
        if len(segments) <= self.max_segments:
            whole = payload(set(range(len(segments))))
            if payload_bytes(whole) <= self.max_bytes:
                return whole
        radius = min(3, (self.max_segments - 1) // 2)
        for index in order:
            group = set(range(max(0, index - radius), min(len(segments), index + radius + 1)))
            proposed = selected | group
            if (
                len(proposed) <= self.max_segments
                and payload_bytes(payload(proposed)) <= self.max_bytes
            ):
                selected = proposed
        if not any(segments[i].speaker_id == speaker_id for i in selected):
            # Never silently send a context without the speaker being resolved.
            raise AnalysisBudgetError
        return payload(selected)
