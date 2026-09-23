class TranscriptCanonicalizationError(Exception):
    code = "canonicalization_failed"
    message = "Transcript canonicalization failed"
    http_status = 503

    def __init__(self):
        super().__init__(self.message)


class CanonicalizationValidationError(TranscriptCanonicalizationError):
    code = "canonicalization_invalid_output"
    message = "Canonicalization returned invalid or incomplete segments"
    http_status = 502


class CanonicalizationProviderError(TranscriptCanonicalizationError):
    code = "canonicalization_provider_unavailable"
    message = "Canonicalization provider request failed"


class CanonicalizationConfigurationError(TranscriptCanonicalizationError):
    code = "canonicalization_not_configured"
    message = "Enable canonicalization and configure model and OPENAI_API_KEY"


class CanonicalizationBusyError(TranscriptCanonicalizationError):
    code = "canonicalization_busy"
    message = "Transcript canonicalization capacity is busy"
    http_status = 429


class CanonicalizationInputError(TranscriptCanonicalizationError):
    code = "canonicalization_input_too_large"
    message = "A transcript segment exceeds the configured batch budget"
    http_status = 422


class CanonicalizationPersistenceError(TranscriptCanonicalizationError):
    code = "canonicalization_persistence_failed"
    message = "Could not read or save canonical transcript"
