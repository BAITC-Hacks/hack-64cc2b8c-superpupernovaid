class MeetingProcessingError(Exception):
    http_status = 503
    code = "meeting_processing_failed"
    message = "Meeting processing failed; retry the operation"


class ProcessingConflict(MeetingProcessingError):
    http_status = 409
    code = "meeting_processing_conflict"
    message = "Another input is processing or the current recording has changed"


class ProcessingNotFound(MeetingProcessingError):
    http_status = 404
    code = "processing_input_not_found"
    message = "Meeting, recording or processing run not found"


class ProcessingConfigurationError(MeetingProcessingError):
    code = "processing_not_configured"
    message = "Configure speech, canonicalization and meeting analysis before processing"


class ProcessingLanguageError(MeetingProcessingError):
    http_status = 422
    code = "processing_language_unsupported"
    message = "The configured cloud speech path currently supports Russian meetings only"


class ProcessingQueueError(MeetingProcessingError):
    code = "processing_queue_unavailable"
    message = "Processing queue unavailable; retry the operation"
