import asyncio
from dataclasses import replace
from threading import Event

import pytest

from app.application.ports import FileStorageError
from app.audio.config import AudioProcessingConfig
from app.audio.errors import (
    AudioConversionError,
    AudioPersistenceError,
    AudioProcessingBusyError,
    AudioProcessingTimeoutError,
    AudioStreamNotFoundError,
    NormalizedAudioStorageError,
)


def test_processing_preserves_source_and_metadata(preprocessor, converter, storage, media):
    before = dict(vars(media))
    audio = asyncio.run(preprocessor.process(media))
    assert vars(media) == before
    assert audio.source_media_id == media.id
    assert audio.sample_rate == 16000 and audio.channels == 1
    assert audio.storage_key != media.storage_key and "/processed/" in audio.storage_key
    with storage.open(media.storage_key) as stream:
        assert stream.read() == b"immutable original media"
    with storage.open(audio.storage_key) as stream:
        assert stream.read() == b"normalized audio bytes"


def test_config_and_cache_key(preprocessor, converter, media):
    first = asyncio.run(preprocessor.process(media))
    preprocessor.config = AudioProcessingConfig(
        sample_rate=48000, channels=2, codec="flac", format="flac"
    )
    second = asyncio.run(preprocessor.process(media))
    assert converter.config.sample_rate == 48000 and converter.config.channels == 2
    assert second.codec == second.format == "flac"
    assert first.config_hash != second.config_hash and first.storage_key != second.storage_key


def test_valid_artifact_is_reused(preprocessor, converter, media):
    first = asyncio.run(preprocessor.process(media))
    second = asyncio.run(preprocessor.process(media))
    assert first.id == second.id
    assert converter.calls == 1


@pytest.mark.parametrize("corrupt", [True, False])
def test_missing_or_corrupt_cache_rebuilt(preprocessor, converter, storage, media, corrupt):
    first = asyncio.run(preprocessor.process(media))
    storage.delete(first.storage_key)
    if corrupt:
        storage.save(first.storage_key, [b"corrupt"], "audio/wav")
    second = asyncio.run(preprocessor.process(media))
    assert second.id != first.id and converter.calls == 2


def test_storage_outage_does_not_invalidate_cache(
    preprocessor, converter, storage, media, repository, monkeypatch
):
    first = asyncio.run(preprocessor.process(media))

    def fail(*args):
        raise FileStorageError("unavailable")

    monkeypatch.setattr(storage, "open", fail)
    with pytest.raises(NormalizedAudioStorageError):
        asyncio.run(preprocessor.process(media))
    assert repository.find(media.id, preprocessor.config.fingerprint).id == first.id
    assert converter.calls == 1


def test_no_audio(preprocessor, converter, media):
    media.audio_codec = None
    with pytest.raises(AudioStreamNotFoundError):
        asyncio.run(preprocessor.process(media))
    assert converter.calls == 0


@pytest.mark.parametrize("error", [AudioConversionError, AudioProcessingTimeoutError])
def test_failed_conversion_leaves_no_artifact(preprocessor, converter, media, storage, error):
    converter.error = error("private stderr")
    with pytest.raises(error):
        asyncio.run(preprocessor.process(media))
    assert list(storage.root.rglob("speech_input.*")) == []
    assert preprocessor.capacity.acquire(blocking=False)
    preprocessor.capacity.release()


def test_database_failure_removes_derived_only(
    preprocessor, repository, media, storage, monkeypatch
):
    def fail(*args):
        raise AudioPersistenceError()

    monkeypatch.setattr(repository, "add_or_get", fail)
    with pytest.raises(AudioPersistenceError):
        asyncio.run(preprocessor.process(media))
    assert list(storage.root.rglob("speech_input.*")) == []
    with storage.open(media.storage_key) as stream:
        assert stream.read(1)


def test_invalid_converter_output_rejected(preprocessor, converter, media, monkeypatch):
    real = converter.convert

    def mismatch(source, output, config):
        return replace(real(source, output, config), sample_rate=48000)

    monkeypatch.setattr(converter, "convert", mismatch)
    with pytest.raises(AudioConversionError):
        asyncio.run(preprocessor.process(media))


def test_capacity_and_cancellation_keep_event_loop_responsive(
    preprocessor, converter, media, monkeypatch
):
    started, release = Event(), Event()
    original = converter.convert

    def slow(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(converter, "convert", slow)

    async def scenario():
        task = asyncio.create_task(preprocessor.process(media))
        assert await asyncio.to_thread(started.wait, 2)
        try:
            # This executes while converter is blocked: the event loop is not blocked.
            with pytest.raises(AudioProcessingBusyError):
                await preprocessor.process(media)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(AudioProcessingBusyError):
                await preprocessor.process(media)
        finally:
            release.set()
        for _ in range(100):
            if preprocessor.capacity.acquire(blocking=False):
                preprocessor.capacity.release()
                return
            await asyncio.sleep(0.01)
        pytest.fail("Processing capacity leaked")

    asyncio.run(scenario())
