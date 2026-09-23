class AudioProcessingError(Exception):
    code = "audio_processing_error"
    message = "Audio preprocessing failed."
    http_status = 422


class AudioStreamNotFoundError(AudioProcessingError):
    code = "audio_stream_not_found"
    message = "The source contains no usable audio stream."


class UnsupportedAudioError(AudioProcessingError):
    code = "unsupported_audio"
    message = "The source is not valid for audio preprocessing."


class AudioConversionError(AudioProcessingError):
    code = "audio_conversion_failed"
    message = "Audio could not be decoded or the output failed validation."


class AudioProcessingTimeoutError(AudioProcessingError):
    code = "audio_processing_timeout"
    message = "Audio preprocessing exceeded its configured time limit."
    http_status = 504


class AudioToolUnavailableError(AudioProcessingError):
    code = "audio_tool_unavailable"
    message = "The audio conversion tools are unavailable."
    http_status = 503


class NormalizedAudioStorageError(AudioProcessingError):
    code = "audio_storage_unavailable"
    message = "Audio storage is temporarily unavailable."
    http_status = 503


class AudioPersistenceError(AudioProcessingError):
    code = "audio_database_unavailable"
    message = "Audio artifact registration is temporarily unavailable."
    http_status = 503


class AudioProcessingBusyError(AudioProcessingError):
    code = "audio_processing_busy"
    message = "Audio processing capacity is busy. Retry later."
    http_status = 429
