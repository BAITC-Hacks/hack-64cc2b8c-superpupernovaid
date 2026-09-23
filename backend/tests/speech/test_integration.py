"""Opt-in local model smoke checks. Never download weights; no real secrets required."""

import asyncio
import hashlib
import os
import wave
from pathlib import Path
from uuid import uuid4

import pytest

from app.audio.models import NormalizedAudio
from app.media.storage import LocalMediaStorage
from app.speech.adapters.asr import NemoSpeechRecognizer, WhisperSpeechRecognizer
from app.speech.adapters.audio import AudioFiles
from app.speech.adapters.diarization import NemoSpeakerDiarizer, PyannoteSpeakerDiarizer
from app.speech.dependencies import configure_offline_runtime
from app.speech.models import DiarizationResult, TranscriptionResult

pytestmark = [pytest.mark.integration, pytest.mark.gpu]


@pytest.mark.parametrize(
    "adapter_type,model_env,method,result_type",
    [
        pytest.param(
            NemoSpeechRecognizer,
            "NEMO_ASR_MODEL",
            "transcribe",
            TranscriptionResult,
            marks=pytest.mark.nemo,
        ),
        pytest.param(
            WhisperSpeechRecognizer,
            "WHISPER_MODEL",
            "transcribe",
            TranscriptionResult,
            marks=pytest.mark.whisper,
        ),
        pytest.param(
            NemoSpeakerDiarizer,
            "NEMO_DIARIZATION_MODEL",
            "diarize",
            DiarizationResult,
            marks=pytest.mark.nemo,
        ),
        pytest.param(
            PyannoteSpeakerDiarizer,
            "PYANNOTE_MODEL",
            "diarize",
            DiarizationResult,
            marks=pytest.mark.pyannote,
        ),
    ],
)
def test_local_model(adapter_type, model_env, method, result_type):
    if os.getenv("RUN_SPEECH_INTEGRATION") != "1":
        pytest.skip("Set RUN_SPEECH_INTEGRATION=1 with provisioned local models/audio")
    model = os.getenv(model_env, "")
    if not model:
        pytest.skip(f"Selected adapter requires {model_env}")
    sample = Path(os.environ["SPEECH_TEST_AUDIO"]).resolve()
    digest = hashlib.sha256()
    with sample.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    with wave.open(str(sample), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    audio = NormalizedAudio(
        id=uuid4(),
        storage_key=sample.name,
        format="wav",
        codec="pcm_s16le",
        sample_rate=16000,
        channels=1,
        size_bytes=sample.stat().st_size,
        sha256=digest.hexdigest(),
        duration_seconds=duration,
    )
    configure_offline_runtime()
    adapter = adapter_type(
        model, os.getenv("SPEECH_TEST_DEVICE", "cuda"), AudioFiles(LocalMediaStorage(sample.parent))
    )
    try:
        result = asyncio.run(getattr(adapter, method)(audio))
        assert isinstance(result, result_type)
        assert result.segments, "Use a short, non-silent, consented speech fixture"
        assert all(0 <= s.start < s.end <= duration + 0.1 for s in result.segments)
        assert asyncio.run(getattr(adapter, method)(audio)).segments
    finally:
        adapter.close()
