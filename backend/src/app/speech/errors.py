class SpeechProcessingError(Exception):
    code = "speech_processing_failed"
    message = "Speech processing failed"
    http_status = 503

    def __init__(self):
        super().__init__(self.message)


class SpeechRecognitionError(SpeechProcessingError):
    code = "speech_recognition_failed"
    message = "Speech recognition failed or returned invalid timestamps"
    http_status = 422


class DiarizationError(SpeechProcessingError):
    code = "diarization_failed"
    message = "Speaker diarization failed"
    http_status = 422


class SpeechAlignmentError(SpeechProcessingError):
    code = "speech_alignment_failed"
    message = "Speech alignment failed"
    http_status = 422


class SpeechModelInitializationError(SpeechProcessingError):
    code = "speech_model_unavailable"
    message = "Local speech model could not be initialized; check model and device configuration"


class InvalidSpeechProviderError(SpeechProcessingError):
    code = "invalid_speech_configuration"
    message = "Invalid speech provider configuration"

    def __init__(self, setting=None, requirement=None):
        if setting is not None:
            self.message = f"{setting}: {requirement}"
        super().__init__()


class SpeechDisabledError(SpeechProcessingError):
    code = "speech_disabled"
    message = "Speech is disabled; configure providers and enable SPEECH_ENABLED"


class SpeechBusyError(SpeechProcessingError):
    code = "speech_busy"
    message = "Speech processing capacity is busy"
    http_status = 429


class SpeechAudioError(SpeechProcessingError):
    code = "speech_audio_invalid"
    message = "Speech requires intact WAV PCM16 mono 16000 Hz within configured resource limits"
    http_status = 422


class SpeechPersistenceError(SpeechProcessingError):
    code = "speech_persistence_failed"
    message = "Could not read or save transcript"


class SpeechCloudError(SpeechProcessingError):
    code = "speech_cloud_unavailable"
    message = "NVIDIA speech request failed; check credentials, quota and service availability"
    http_status = 502


class SpeechCloudAudioTooLarge(SpeechProcessingError):
    code = "speech_cloud_audio_too_large"
    message = "Normalized WAV exceeds NVIDIA_MAX_AUDIO_BYTES; long-form streaming is not enabled"
    http_status = 413
