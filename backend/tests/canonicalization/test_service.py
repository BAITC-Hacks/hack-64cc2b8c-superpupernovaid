import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.canonicalization.batching import make_batches
from app.canonicalization.errors import (
    CanonicalizationBusyError,
    CanonicalizationInputError,
    CanonicalizationProviderError,
    CanonicalizationValidationError,
)
from app.canonicalization.models import CanonicalizationBatchResult, CanonicalizedSegmentOutput
from app.canonicalization.repository import CanonicalTranscriptRecord
from app.speech.models import AttributedTranscript


def test_full_transform_preserves_source_and_reuses_persistence(service, transcript, fake, engine):
    original = transcript.model_dump_json()
    result = asyncio.run(service.canonicalize(transcript))
    assert transcript.model_dump_json() == original
    assert result.source_audio_id == transcript.source_audio_id
    assert result.canonical_language == "ru"
    for before, after in zip(transcript.segments, result.segments, strict=True):
        assert (before.id, before.start, before.end, before.speaker_id, before.text) == (
            after.id,
            after.start,
            after.end,
            after.speaker_id,
            after.original_text,
        )
    assert result.segments[0].canonical_text == "Данияр, закройте эту задачу до пятницы."
    assert result.segments[1].canonical_text == "Отправьте завтра до обеда."
    assert result.segments[2].canonical_text == "Задеплойте Kubernetes в staging."
    assert "поручено" not in result.segments[3].canonical_text
    assert len(fake.calls) == 2
    assert [s.id for s in fake.calls[1].context] == ["seg_1"]
    assert asyncio.run(service.canonicalize(transcript)) == result
    assert len(fake.calls) == 2
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CanonicalTranscriptRecord)) == 1


def test_exact_original_whitespace_unicode_and_changed_source_cache(service, transcript, fake):
    transcript.segments[0] = transcript.segments[0].model_copy(update={"text": "  Сәле́м\n\t  "})
    first = asyncio.run(service.canonicalize(transcript))
    assert first.segments[0].original_text == "  Сәле́м\n\t  "
    transcript.segments[0] = transcript.segments[0].model_copy(update={"text": "Другой текст"})
    second = asyncio.run(service.canonicalize(transcript))
    assert second.segments[0].original_text == "Другой текст"
    assert len(fake.calls) == 4


@pytest.mark.parametrize("fault", ["unknown", "missing", "duplicate", "context"])
def test_rejects_damaged_batch_without_partial_persistence(
    service, transcript, fake, engine, fault
):
    async def invalid(batch):
        ids = [s.id for s in batch.targets]
        if fault == "missing":
            ids = ids[:-1]
        if fault == "duplicate":
            ids[-1] = ids[0]
        if fault == "unknown":
            ids[-1] = "not-an-input-id"
        if fault == "context":
            ids.append("context-only-id")
        return CanonicalizationBatchResult(
            segments=[
                CanonicalizedSegmentOutput(id=id, canonical_text="text", uncertain=False)
                for id in ids
            ]
        )

    fake.canonicalize_batch = invalid
    with pytest.raises(CanonicalizationValidationError):
        asyncio.run(service.canonicalize(transcript))
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CanonicalTranscriptRecord)) == 0


def test_empty_transcript_calls_no_model(service, fake):
    transcript = AttributedTranscript(source_audio_id=uuid4(), segments=[])
    result = asyncio.run(service.canonicalize(transcript))
    assert result.segments == [] and fake.calls == []


def test_partial_failure_cancels_peers_and_saves_nothing(service, transcript, fake, engine):
    cancelled = []

    async def call(batch):
        if batch.targets[0].id == "seg_0":
            await asyncio.sleep(0.01)
            raise CanonicalizationProviderError
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.append(True)

    fake.canonicalize_batch = call
    with pytest.raises(CanonicalizationProviderError):
        asyncio.run(service.canonicalize(transcript))
    assert cancelled == [True]
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CanonicalTranscriptRecord)) == 0


def test_concurrency_and_disconnect_keep_admission_until_completion(service, transcript, fake):
    service.settings.canonicalization_batch_max_segments = 1
    service.settings.canonicalization_max_concurrency = 2
    active, peak = 0, 0
    original = fake.canonicalize_batch

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(batch):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.set()
            try:
                await release.wait()
                return await original(batch)
            finally:
                active -= 1

        fake.canonicalize_batch = delayed
        request = asyncio.create_task(service.canonicalize(transcript))
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(CanonicalizationBusyError):
            await service.canonicalize(transcript)
        release.set()
        await service.close()
        assert peak == 2 and active == 0

    asyncio.run(run())


def test_batch_byte_limit_counts_context_and_utf8(transcript):
    batches = make_batches(
        transcript, language="kk", max_segments=3, max_bytes=300, context_segments=2
    )
    assert [s.id for b in batches for s in b.targets] == [s.id for s in transcript.segments]
    assert all(len(b.payload("kk").encode()) <= 300 for b in batches)


def test_oversized_late_segment_rejected_before_first_call(service, transcript, fake):
    transcript.segments[-1] = transcript.segments[-1].model_copy(update={"text": "Қ" * 10000})
    with pytest.raises(CanonicalizationInputError):
        asyncio.run(service.canonicalize(transcript))
    assert not fake.calls
