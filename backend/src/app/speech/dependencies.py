import hashlib
import importlib.metadata
import json
import os
from functools import lru_cache
from pathlib import Path

from app.audio.repository import AudioRepository
from app.bootstrap import get_media_storage
from app.config import Settings, get_settings
from app.speech.adapters.asr import NemoSpeechRecognizer, WhisperSpeechRecognizer
from app.speech.adapters.audio import AudioFiles
from app.speech.adapters.diarization import NemoSpeakerDiarizer, PyannoteSpeakerDiarizer
from app.speech.adapters.nvidia import NvidiaSpeechAdapter
from app.speech.alignment import SpeakerTranscriptAligner
from app.speech.errors import InvalidSpeechProviderError
from app.speech.interfaces import SpeakerDiarizer, SpeechRecognizer
from app.speech.repository import SpeechRepository
from app.speech.service import SpeechService


def validate_speech_configuration(settings: Settings, *, check_packages=True):
    if settings.asr_provider not in {
        "nemo",
        "whisper",
        "nvidia",
    } or settings.diarization_provider not in {
        "nemo",
        "pyannote",
        "nvidia",
    }:
        raise InvalidSpeechProviderError
    if not settings.speech_enabled:
        return
    if "nvidia" in (settings.asr_provider, settings.diarization_provider):
        if (settings.asr_provider, settings.diarization_provider) != ("nvidia", "nvidia"):
            raise InvalidSpeechProviderError(
                "providers", "select nvidia for both ASR and diarization"
            )
        if not settings.nvidia_api_key or not settings.nvidia_api_key.get_secret_value().strip():
            raise InvalidSpeechProviderError("NVIDIA_API_KEY", "required for cloud speech")
        if check_packages:
            try:
                importlib.metadata.version("nvidia-riva-client")
            except importlib.metadata.PackageNotFoundError:
                raise InvalidSpeechProviderError(
                    "nvidia-riva-client", "install cloud runtime"
                ) from None
        return
    selected = [
        (settings.nemo_asr_model, "file", "nemo_toolkit", "NEMO_ASR_MODEL")
        if settings.asr_provider == "nemo"
        else (settings.whisper_model, "directory", "faster-whisper", "WHISPER_MODEL"),
        (settings.nemo_diarization_model, "file", "nemo_toolkit", "NEMO_DIARIZATION_MODEL")
        if settings.diarization_provider == "nemo"
        else (settings.pyannote_model, "directory", "pyannote.audio", "PYANNOTE_MODEL"),
    ]
    for name, kind, package, setting in selected:
        path = Path(name)
        if (
            not name
            or not path.is_absolute()
            or not (path.is_file() and path.suffix == ".nemo" if kind == "file" else path.is_dir())
        ):
            raise InvalidSpeechProviderError(setting, f"expected an existing absolute local {kind}")
        if check_packages:
            try:
                importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError as exc:
                raise InvalidSpeechProviderError(
                    setting, f"install optional {package} runtime"
                ) from exc


def configure_offline_runtime():
    # No inference downloads or telemetry. Model provisioning is explicitly separate.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"


def speech_profile(settings):
    if settings.asr_provider == "nvidia":
        profile = {
            "pipeline": "nvidia-riva-diar-v1",
            "function": settings.nvidia_asr_function_id,
            "language": settings.nvidia_language_code,
            "max_speakers": 4,
            "revision": settings.speech_model_revision,
        }
        return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    # Secrets, unrelated providers and credentials do not influence persisted results.
    profile = {
        "pipeline": "speech-v1-word-core25-context2.5-overlap0.5-margin0.1-min0.05",
        "revision": settings.speech_model_revision,
        "asr": settings.asr_provider,
        "diarization": settings.diarization_provider,
        "asr_model": settings.nemo_asr_model
        if settings.asr_provider == "nemo"
        else settings.whisper_model,
        "diarization_model": settings.nemo_diarization_model
        if settings.diarization_provider == "nemo"
        else settings.pyannote_model,
        "asr_device": settings.nemo_device
        if settings.asr_provider == "nemo"
        else settings.whisper_device,
        "diarization_device": settings.nemo_device
        if settings.diarization_provider == "nemo"
        else settings.pyannote_device,
        "whisper_compute_type": settings.whisper_compute_type
        if settings.asr_provider == "whisper"
        else None,
    }
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


@lru_cache
def get_speech_files():
    settings = get_settings()
    return AudioFiles(
        get_media_storage(),
        settings.speech_max_duration_seconds,
        settings.speech_diarization_max_decoded_bytes,
    )


@lru_cache
def get_nvidia_speech_adapter():
    return NvidiaSpeechAdapter(get_settings(), get_speech_files())


@lru_cache
def get_speech_recognizer() -> SpeechRecognizer:
    s, files = get_settings(), get_speech_files()
    match s.asr_provider:
        case "nvidia":
            return get_nvidia_speech_adapter()
        case "nemo":
            return NemoSpeechRecognizer(s.nemo_asr_model, s.nemo_device, files)
        case "whisper":
            return WhisperSpeechRecognizer(
                s.whisper_model, s.whisper_device, files, s.whisper_compute_type
            )
        case _:
            raise InvalidSpeechProviderError


@lru_cache
def get_speaker_diarizer() -> SpeakerDiarizer:
    s, files = get_settings(), get_speech_files()
    match s.diarization_provider:
        case "nvidia":
            return get_nvidia_speech_adapter()
        case "nemo":
            return NemoSpeakerDiarizer(s.nemo_diarization_model, s.nemo_device, files)
        case "pyannote":
            return PyannoteSpeakerDiarizer(s.pyannote_model, s.pyannote_device, files)
        case _:
            raise InvalidSpeechProviderError


@lru_cache
def get_speech_service() -> SpeechService | None:
    s = get_settings()
    if not s.speech_enabled:
        return None
    return SpeechService(
        get_speech_recognizer(),
        get_speaker_diarizer(),
        SpeakerTranscriptAligner(),
        SpeechRepository(),
        speech_profile(s),
        validate_audio=get_speech_files().validate_metadata,
    )


@lru_cache
def get_speech_audio_repository():
    return AudioRepository()


async def shutdown_speech():
    # Lifespan constructs the service once at startup, but loads models only on first use.
    service = get_speech_service()
    if service is not None:
        await service.close()
    for factory in (
        get_speech_service,
        get_nvidia_speech_adapter,
        get_speech_recognizer,
        get_speaker_diarizer,
        get_speech_files,
        get_speech_audio_repository,
    ):
        factory.cache_clear()
