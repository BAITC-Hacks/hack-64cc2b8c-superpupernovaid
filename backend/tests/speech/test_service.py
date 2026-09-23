import asyncio
import threading

import pytest

from app.speech.errors import SpeechBusyError, SpeechProcessingError
from app.speech.models import DiarizationResult
from app.speech.repository import SpeechRepository


def test_pipeline_persists_and_reuses_stable_result(service, audio, engine):
    first = asyncio.run(service.process(audio))
    second = asyncio.run(service.process(audio))
    assert first == second
    assert first.source_audio_id == audio.id
    assert first.segments[0].text == "Привет"
    assert first.segments[0].speaker_id == "SPEAKER_00"
    assert service.recognizer.calls == service.diarizer.calls == 1
    assert SpeechRepository(engine).find(audio.id, "a" * 64) == first
    # Different provider/model profile cannot return the old result.
    assert SpeechRepository(engine).find(audio.id, "b" * 64) is None


def test_cancellation_keeps_slot_and_event_loop_live(service, audio):
    started, release = threading.Event(), threading.Event()
    original = service.recognizer.transcribe

    async def slow(audio):
        def wait():
            started.set()
            release.wait(5)

        await asyncio.to_thread(wait)
        return await original(audio)

    service.recognizer.transcribe = slow

    async def run():
        request = asyncio.create_task(service.process(audio))
        while not started.is_set():
            await asyncio.sleep(0.001)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(SpeechBusyError):
            await service.process(audio)
        assert service.diarizer.calls == 0  # Sequential: no second GPU job overlaps.
        release.set()
        await service.close()
        assert service.diarizer.calls == 1
        with pytest.raises(SpeechBusyError):
            await service.process(audio)

    asyncio.run(run())


def test_native_exception_is_controlled_and_slot_released(service, audio, caplog):
    async def fail(audio):
        raise RuntimeError("private transcript and key")

    service.recognizer.transcribe = fail
    for _ in range(2):
        with pytest.raises(SpeechProcessingError):
            asyncio.run(service.process(audio))
    assert "private transcript and key" not in caplog.text
    assert service.diarizer.calls == 0


def test_invalid_global_timestamps_not_saved(service, audio, engine):
    async def invalid(audio):
        return DiarizationResult(segments=[dict(start=0, end=100, speaker_id="SPEAKER_00")])

    service.diarizer.diarize = invalid
    with pytest.raises(SpeechProcessingError):
        asyncio.run(service.process(audio))
    assert SpeechRepository(engine).find(audio.id, "a" * 64) is None


def test_resource_admission_runs_before_any_provider(service, audio):
    from app.speech.errors import SpeechAudioError

    def refuse(audio):
        raise SpeechAudioError

    service.validate_audio = refuse
    with pytest.raises(SpeechAudioError):
        asyncio.run(service.process(audio))
    assert service.recognizer.calls == service.diarizer.calls == 0
