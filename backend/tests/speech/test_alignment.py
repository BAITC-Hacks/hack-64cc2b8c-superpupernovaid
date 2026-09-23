from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.speech.alignment import SpeakerTranscriptAligner
from app.speech.models import DiarizationResult, TranscriptionResult, TranscriptionSegment


@pytest.mark.parametrize(
    "span,turns,expected",
    [
        ((0, 1), [(0, 1, "SPEAKER_00")], "SPEAKER_00"),
        ((5, 10), [(4, 6, "SPEAKER_00"), (6, 11, "SPEAKER_01")], "SPEAKER_01"),
        ((0, 1), [(0, 0.5, "SPEAKER_00"), (0.5, 1, "SPEAKER_01")], "UNKNOWN"),
        ((1, 2), [(0, 1, "SPEAKER_00")], "UNKNOWN"),
        ((0, 1), [(0, 1, "SPEAKER_00"), (0, 1, "SPEAKER_01")], "UNKNOWN"),
        ((0, 0.01), [(0, 0.01, "SPEAKER_00")], "UNKNOWN"),
        ((0, 1), [(0, 0.04, "SPEAKER_00")], "UNKNOWN"),
        ((0, 1), [], "UNKNOWN"),
        ((0, 1), [(0, 0.3, "SPEAKER_00"), (0.3, 0.8, "SPEAKER_00")], "SPEAKER_00"),
        ((0, 1), [(0, 0.3, "SPEAKER_00"), (0, 0.3, "SPEAKER_00")], "UNKNOWN"),
    ],
)
def test_conservative_overlap(span, turns, expected):
    asr = TranscriptionResult(segments=[dict(start=span[0], end=span[1], text="Текст")])
    diar = DiarizationResult(segments=[dict(start=s, end=e, speaker_id=k) for s, e, k in turns])
    result = SpeakerTranscriptAligner().align(asr, diar, source_audio_id=uuid4())
    assert result.segments[0].speaker_id == expected
    assert (result.segments[0].start, result.segments[0].end) == span


def test_ids_stable_when_unrelated_segment_inserted_and_unique_for_duplicates():
    aligner, audio_id = SpeakerTranscriptAligner(), uuid4()
    old = dict(start=1, end=2, text="Реплика")
    diar = DiarizationResult(segments=[])
    before = aligner.align(TranscriptionResult(segments=[old, old]), diar, source_audio_id=audio_id)
    after = aligner.align(
        TranscriptionResult(segments=[dict(start=0, end=0.5, text="Новая"), old, old]),
        diar,
        source_audio_id=audio_id,
    )
    assert [s.id for s in before.segments] == [s.id for s in after.segments[1:]]
    assert len({s.id for s in before.segments}) == 2
    other = aligner.align(TranscriptionResult(segments=[old]), diar, source_audio_id=uuid4())
    assert other.segments[0].id != before.segments[0].id


def test_empty_transcription():
    result = SpeakerTranscriptAligner().align(
        TranscriptionResult(segments=[]), DiarizationResult(segments=[]), source_audio_id=uuid4()
    )
    assert result.segments == []


@pytest.mark.parametrize(
    "start,end", [(0, 0), (2, 1), (-1, 2), (0, float("inf")), (float("nan"), 2)]
)
def test_invalid_timestamps(start, end):
    with pytest.raises(ValidationError):
        TranscriptionSegment(start=start, end=end, text="test")
