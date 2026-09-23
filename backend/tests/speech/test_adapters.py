import asyncio
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.speech.adapters.asr import NemoSpeechRecognizer, WhisperSpeechRecognizer, append_words
from app.speech.adapters.audio import AudioFiles, AudioWindow
from app.speech.adapters.diarization import NemoSpeakerDiarizer, PyannoteSpeakerDiarizer
from app.speech.errors import (
    SpeechAudioError,
    SpeechModelInitializationError,
    SpeechRecognitionError,
)
from app.speech.models import DiarizationResult, TranscriptionResult


def test_whisper_translation_and_lazy_load_once(audio, storage, monkeypatch):
    loads = []

    class Native:
        def transcribe(self, path, **kwargs):
            assert kwargs["word_timestamps"] and not kwargs["vad_filter"]
            return iter(
                [
                    SimpleNamespace(
                        text="test", words=[SimpleNamespace(start=0, end=0.8, word="test")]
                    )
                ]
            ), object()

    adapter = WhisperSpeechRecognizer("local", "cpu", AudioFiles(storage))

    def load():
        loads.append(1)
        return Native()

    monkeypatch.setattr(adapter, "_load", load)
    first = asyncio.run(adapter.transcribe(audio))
    second = asyncio.run(adapter.transcribe(audio))
    assert isinstance(first, TranscriptionResult) and first == second
    assert loads == [1]
    adapter.close()
    assert adapter._model is None


def test_nemo_word_dto_and_no_synthetic_timestamps(audio, storage):
    adapter = NemoSpeechRecognizer("local", "cpu", AudioFiles(storage))
    adapter._model = SimpleNamespace(
        transcribe=lambda *a, **kw: [
            SimpleNamespace(
                timestamp={"word": [dict(start=0.1, end=0.8, word="Сәлем")]}, text="Сәлем"
            )
        ]
    )
    assert asyncio.run(adapter.transcribe(audio)).segments[0].text == "Сәлем"
    adapter._model = SimpleNamespace(transcribe=lambda *a, **kw: ["unsupported text-only model"])
    with pytest.raises(SpeechRecognitionError):
        asyncio.run(adapter.transcribe(audio))


@pytest.mark.parametrize("kind", ["nemo", "pyannote"])
def test_diarizer_outputs_global_labels(audio, storage, kind):
    files = AudioFiles(storage)
    if kind == "nemo":
        adapter = NemoSpeakerDiarizer("local", "cpu", files)
        adapter._model = SimpleNamespace(
            diarize=lambda **kw: [["0.0 0.4 speaker_7", "0.2 0.6 speaker_9", "0.6 1.0 speaker_7"]]
        )
    else:
        adapter = PyannoteSpeakerDiarizer("local", "cpu", files)
        annotation = SimpleNamespace(
            itertracks=lambda **kw: [
                (SimpleNamespace(start=0, end=0.4), 0, "native-a"),
                (SimpleNamespace(start=0.2, end=0.6), 0, "native-b"),
                (SimpleNamespace(start=0.6, end=1), 0, "native-a"),
            ]
        )
        adapter._model = lambda path: SimpleNamespace(speaker_diarization=annotation)
    result = asyncio.run(adapter.diarize(audio))
    assert isinstance(result, DiarizationResult)
    assert [s.speaker_id for s in result.segments] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]


def test_resource_limit_and_integrity(audio, storage):
    with pytest.raises(SpeechAudioError):
        with AudioFiles(storage, max_decoded_bytes=1).local(audio, diarization=True):
            pass
    audio.sha256 = "0" * 64
    with pytest.raises(SpeechAudioError):
        with AudioFiles(storage).local(audio):
            pass


def test_windows_are_bounded_and_preserve_timeline(tmp_path):
    path = tmp_path / "source.wav"
    with wave.open(str(path), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for _ in range(61):
            f.writeframesraw(b"\x00" * 32000)
    windows = []
    for window in AudioFiles(None).windows(path):
        with wave.open(str(window.path), "rb") as f:
            assert f.getnframes() <= 30 * 16000
        windows.append((window.offset, window.keep_start, window.keep_end))
    assert windows == [(0, 0, 25), (22.5, 25, 50), (47.5, 50, 61)]


def test_overlapping_windows_word_ownership():
    words = []
    append_words(words, [(24, 25.5, "boundary")], AudioWindow(Path("a"), 0, 0, 25))
    append_words(
        words, [(1.5, 3, "boundary"), (3, 4, "next")], AudioWindow(Path("b"), 22.5, 25, 50)
    )
    assert [w.text for w in words] == ["boundary", "next"]
    assert words[1].start == 25.5


def test_initialization_failure_is_sanitized_and_cached(audio, storage, monkeypatch):
    adapter = WhisperSpeechRecognizer("local", "cpu", AudioFiles(storage))
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("native secret")

    monkeypatch.setattr(adapter, "_load", fail)
    for _ in range(2):
        with pytest.raises(SpeechModelInitializationError) as err:
            asyncio.run(adapter.transcribe(audio))
        assert "native secret" not in str(err.value)
    assert calls == [1]


def test_storage_reads_are_bounded(audio, storage):
    from contextlib import contextmanager

    sizes = []

    class BoundedStorage:
        @contextmanager
        def open(self, key):
            with storage.open(key) as stream:

                class Reader:
                    def read(self, size):
                        assert 0 < size <= 1024 * 1024
                        sizes.append(size)
                        return stream.read(size)

                yield Reader()

    with AudioFiles(BoundedStorage()).local(audio) as path:
        assert path.exists()
    assert sizes and not path.exists()


def test_concurrent_calls_initialize_model_only_once(audio, storage, monkeypatch):
    import threading

    adapter = WhisperSpeechRecognizer("local", "cpu", AudioFiles(storage))
    count = []

    def load():
        count.append(threading.get_ident())
        return object()

    monkeypatch.setattr(adapter, "_load", load)
    monkeypatch.setattr(adapter, "_infer", lambda audio: TranscriptionResult(segments=[]))

    async def run():
        main_thread = threading.get_ident()
        await asyncio.gather(adapter.transcribe(audio), adapter.transcribe(audio))
        assert len(count) == 1 and count[0] != main_thread

    asyncio.run(run())
