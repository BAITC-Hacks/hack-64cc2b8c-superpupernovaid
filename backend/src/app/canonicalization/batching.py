import json
from dataclasses import dataclass

from app.canonicalization.errors import CanonicalizationInputError
from app.speech.models import AttributedTranscript, AttributedTranscriptSegment


@dataclass(frozen=True)
class CanonicalizationBatch:
    targets: tuple[AttributedTranscriptSegment, ...]
    context: tuple[AttributedTranscriptSegment, ...] = ()

    def payload(self, language: str) -> str:
        # Timestamps and speaker metadata are not needed by the language transform.
        def item(segment):
            return {"id": segment.id, "text": segment.text}

        return json.dumps(
            {
                "canonical_language": language,
                "context_only_do_not_output": [item(s) for s in self.context],
                "targets": [item(s) for s in self.targets],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def make_batches(
    transcript: AttributedTranscript,
    *,
    language: str,
    max_segments: int,
    max_bytes: int,
    context_segments: int,
) -> list[CanonicalizationBatch]:
    # Plan/validate the WHOLE input before any paid API request; retain only references.
    batches, index = [], 0
    while index < len(transcript.segments):
        context = tuple(transcript.segments[max(0, index - context_segments) : index])
        targets = []
        while index + len(targets) < len(transcript.segments) and len(targets) < max_segments:
            candidate = targets + [transcript.segments[index + len(targets)]]
            trial = CanonicalizationBatch(tuple(candidate), context)
            if len(trial.payload(language).encode("utf-8")) > max_bytes:
                if targets:
                    break
                if context:
                    context = context[1:]
                    continue
                # Never split one source segment or quietly truncate text.
                raise CanonicalizationInputError
            targets = candidate
        batches.append(CanonicalizationBatch(tuple(targets), context))
        index += len(targets)
    return batches
