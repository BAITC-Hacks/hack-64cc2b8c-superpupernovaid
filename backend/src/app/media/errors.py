class MediaError(Exception):
    code = "media_error"
    message = "Media ingestion failed."
    http_status = 500


class UnsupportedMediaError(MediaError):
    code = "unsupported_media"
    message = "This media container is not supported."
    http_status = 415


class InvalidMediaError(MediaError):
    code = "invalid_media"
    message = "The file is empty, damaged, or has no usable audio/video streams."
    http_status = 422


class MediaTooLargeError(MediaError):
    code = "media_too_large"
    message = "The upload exceeds the configured size limit."
    http_status = 413


class MediaStorageError(MediaError):
    code = "media_storage_unavailable"
    message = "Media storage is temporarily unavailable."
    http_status = 503


class MediaProbeError(MediaError):
    code = "media_probe_unavailable"
    message = "Media inspection is unavailable or exceeded its time limit."
    http_status = 503


class MediaPersistenceError(MediaError):
    code = "media_database_unavailable"
    message = "Media registration is temporarily unavailable."
    http_status = 503
