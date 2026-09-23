class ProtocolExportError(Exception):
    code = "protocol_export_failed"
    message = "Protocol export failed"
    http_status = 503

    def __init__(self):
        super().__init__(self.message)


class UnsupportedExportFormatError(ProtocolExportError):
    code = "unsupported_export_format"
    message = "Supported formats: docx, pdf"
    http_status = 422


class ProtocolDocumentRenderError(ProtocolExportError):
    code = "protocol_document_render_failed"
    message = "Could not render document; check export configuration"
    http_status = 422


class ProtocolArtifactStorageError(ProtocolExportError):
    code = "protocol_artifact_storage_failed"
    message = "Export artifact is temporarily unavailable"


class MeetingProtocolNotReadyError(ProtocolExportError):
    code = "meeting_protocol_not_ready"
    message = "A saved transcript and meeting analysis are required before export"
    http_status = 409


class ProtocolMeetingNotFoundError(ProtocolExportError):
    code = "meeting_not_found"
    message = "Meeting not found"
    http_status = 404


class ProtocolExportBusyError(ProtocolExportError):
    code = "protocol_export_busy"
    message = "Another export is running; retry later"
    http_status = 429


class ProtocolExportTooLargeError(ProtocolExportError):
    code = "protocol_export_too_large"
    message = "Protocol exceeds the configured export size limit"
    http_status = 413
