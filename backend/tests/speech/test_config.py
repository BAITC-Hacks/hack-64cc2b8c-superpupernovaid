import logging

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.speech import dependencies as deps
from app.speech.adapters.asr import NemoSpeechRecognizer, WhisperSpeechRecognizer
from app.speech.adapters.diarization import NemoSpeakerDiarizer, PyannoteSpeakerDiarizer
from app.speech.errors import InvalidSpeechProviderError


@pytest.mark.parametrize(
    "asr,diar,asr_type,diar_type",
    [
        ("nemo", "nemo", NemoSpeechRecognizer, NemoSpeakerDiarizer),
        ("whisper", "pyannote", WhisperSpeechRecognizer, PyannoteSpeakerDiarizer),
        ("whisper", "nemo", WhisperSpeechRecognizer, NemoSpeakerDiarizer),
        ("nemo", "pyannote", NemoSpeechRecognizer, PyannoteSpeakerDiarizer),
    ],
)
def test_independent_provider_selection(monkeypatch, asr, diar, asr_type, diar_type):
    settings = Settings(_env_file=None, asr_provider=asr, diarization_provider=diar)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_speech_files", lambda: object())
    assert isinstance(deps.get_speech_recognizer.__wrapped__(), asr_type)
    assert isinstance(deps.get_speaker_diarizer.__wrapped__(), diar_type)


def test_defaults():
    settings = Settings(_env_file=None)
    assert (settings.asr_provider, settings.diarization_provider) == ("nemo", "nemo")
    deps.validate_speech_configuration(settings)  # Disabled: no model imports/downloads.


@pytest.mark.parametrize("field", ["asr_provider", "diarization_provider"])
def test_invalid_provider(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: "foobar"})


def test_models_required_only_for_enabled_selected_providers(tmp_path):
    settings = Settings(_env_file=None, speech_enabled=True)
    with pytest.raises(InvalidSpeechProviderError):
        deps.validate_speech_configuration(settings, check_packages=False)
    model = tmp_path / "model.nemo"
    model.write_bytes(b"test checkpoint placeholder")
    settings.nemo_asr_model = settings.nemo_diarization_model = str(model)
    # NVIDIA key is NOT required for local inference.
    deps.validate_speech_configuration(settings, check_packages=False)


def test_nvidia_secret_is_loaded_but_excluded(monkeypatch, caplog):
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-secret-never-real")
    settings = Settings(_env_file=None)
    assert settings.nvidia_api_key.get_secret_value() == "unit-test-secret-never-real"
    assert "nvidia_api_key" not in settings.model_dump()
    assert "unit-test-secret-never-real" not in repr(settings) + settings.model_dump_json()
    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("settings=%s", settings)
    assert "unit-test-secret-never-real" not in caplog.text


def test_profile_not_changed_by_secret_or_inactive_provider():
    first = Settings(_env_file=None)
    second = Settings(_env_file=None, nvidia_api_key="not-real", whisper_model="elsewhere")
    assert deps.speech_profile(first) == deps.speech_profile(second)
    second.speech_model_revision = "2"
    assert deps.speech_profile(first) != deps.speech_profile(second)
