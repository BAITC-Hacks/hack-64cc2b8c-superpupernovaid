import json
from collections import defaultdict
from uuid import UUID, uuid5

from app.speech.models import (
    AttributedTranscript,
    AttributedTranscriptSegment,
    DiarizationResult,
    TranscriptionResult,
)


class SpeakerTranscriptAligner:
    """Conservative overlap attribution, never infers participant identity."""

    def __init__(self, min_coverage=0.5, min_overlap_seconds=0.05, min_margin=0.1):
        self.min_coverage = min_coverage
        self.min_overlap_seconds = min_overlap_seconds
        self.min_margin = min_margin

    def align(
        self,
        transcription: TranscriptionResult,
        diarization: DiarizationResult,
        *,
        source_audio_id: UUID,
    ) -> AttributedTranscript:
        # Merge intervals for each speaker to avoid double-counting duplicate tracks.
        by_speaker = defaultdict(list)
        for segment in diarization.segments:
            by_speaker[segment.speaker_id].append((segment.start, segment.end))
        turns = []
        for speaker, intervals in by_speaker.items():
            merged = []
            for start, end in sorted(intervals):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            turns.extend((start, end, speaker) for start, end in merged)
        turns.sort()
        active, cursor, occurrences, result = [], 0, defaultdict(int), []
        for segment in sorted(transcription.segments, key=lambda s: (s.start, s.end, s.text)):
            while cursor < len(turns) and turns[cursor][0] < segment.end:
                active.append(turns[cursor])
                cursor += 1
            active = [t for t in active if t[1] > segment.start]
            overlap = defaultdict(float)
            for start, end, speaker in active:
                overlap[speaker] += max(0, min(end, segment.end) - max(start, segment.start))
            ranked = sorted(overlap.items(), key=lambda item: (-item[1], item[0]))
            speaker = "UNKNOWN"
            duration = segment.end - segment.start
            if ranked:
                best = ranked[0][1]
                runner_up = ranked[1][1] if len(ranked) > 1 else 0
                if (
                    best >= self.min_overlap_seconds
                    and best / duration >= self.min_coverage
                    and (best - runner_up) / duration >= self.min_margin
                ):
                    speaker = ranked[0][0]
            # Stable by source + exact utterance, independent of position in the full list.
            identity = json.dumps(
                [segment.start, segment.end, segment.text],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            occurrence = occurrences[identity]
            occurrences[identity] += 1
            result.append(
                AttributedTranscriptSegment(
                    **segment.model_dump(),
                    speaker_id=speaker,
                    id="seg_" + uuid5(source_audio_id, f"{identity}:{occurrence}").hex,
                )
            )
        return AttributedTranscript(source_audio_id=source_audio_id, segments=result)
