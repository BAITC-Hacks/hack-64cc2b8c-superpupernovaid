import asyncio
from types import SimpleNamespace as NS

import pytest

from app.config import Settings
from app.speech.adapters.nvidia import NvidiaSpeechAdapter, parse_response
from app.speech.dependencies import speech_profile, validate_speech_configuration
from app.speech.errors import (
    InvalidSpeechProviderError,
    SpeechCloudAudioTooLarge,
    SpeechRecognitionError,
)


def response(words, transcript="speech"):
    return NS(
        results=[
            NS(
                alternatives=[
                    NS(
                        transcript=transcript,
                        words=[
                            NS(start_time=s, end_time=e, word=t, speaker_tag=tag)
                            for s, e, t, tag in words
                        ],
                    )
                ]
            )
        ]
    )


def test_cloud_timestamps_and_zero_duration_tokens():
    text, diar = parse_response(
        response([(0, 500, "Привет", 0), (500, 500, ",", 0), (600, 900, "да", 1)]), 1
    )
    assert [w.text for w in text.segments] == ["Привет,", "да"]
    assert [s.speaker_id for s in diar.segments] == ["SPEAKER_00", "SPEAKER_01"]
    assert text.segments[1].start == 0.6


@pytest.mark.parametrize(
    "value", [response([]), response([(900, 1400, "нет", 0)]), response([(700, 200, "нет", 0)])]
)
def test_missing_or_invalid_timestamps_rejected(value):
    with pytest.raises(SpeechRecognitionError):
        parse_response(value, 1)


def test_pair_shares_one_request_and_does_not_retain_result(audio, storage, monkeypatch):
    adapter = NvidiaSpeechAdapter(Settings(_env_file=None), None)
    calls = []
    pair = parse_response(response([(0, 900, "да", 0)]), 1)

    def recognize(value):
        calls.append(value.id)
        return pair

    monkeypatch.setattr(adapter, "_recognize", recognize)

    async def run():
        assert await adapter.transcribe(audio) == pair[0]
        assert await adapter.diarize(audio) == pair[1]

    asyncio.run(run())
    assert calls == [audio.id]
    assert adapter.cached is None


def test_cloud_size_rejected_before_storage_read(audio, storage):
    from app.speech.adapters.audio import AudioFiles

    s = Settings(_env_file=None, nvidia_max_audio_bytes=1)
    adapter = NvidiaSpeechAdapter(s, AudioFiles(storage))
    with pytest.raises(SpeechCloudAudioTooLarge):
        adapter._recognize(audio)


def test_cloud_configuration_and_secret_not_in_fingerprint():
    s = Settings(
        _env_file=None,
        speech_enabled=True,
        asr_provider="nvidia",
        diarization_provider="nvidia",
        nvidia_api_key="test",
    )
    validate_speech_configuration(s, check_packages=False)
    before = speech_profile(s)
    s.nvidia_api_key = "different"
    assert speech_profile(s) == before
    s.nvidia_language_code = "en-US"
    assert speech_profile(s) != before
    s.diarization_provider = "nemo"
    with pytest.raises(InvalidSpeechProviderError):
        validate_speech_configuration(s, check_packages=False)


def test_padded_last_frame_clipped_to_real_audio_end():
    text, _ = parse_response(response([(900, 1120, "конец", 0)]), 1)
    assert text.segments[0].end == 1
