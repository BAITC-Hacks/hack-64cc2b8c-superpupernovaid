class MeetingIntelligenceError(Exception):
    code = "meeting_intelligence_failed"
    message = "Meeting analysis could not be completed"
    http_status = 503

    def __init__(self):
        super().__init__(self.message)


class ExtractionAgentError(MeetingIntelligenceError):
    code = "meeting_extraction_failed"


class ResolverAgentError(MeetingIntelligenceError):
    code = "meeting_resolution_failed"


class SummaryAgentError(MeetingIntelligenceError):
    code = "meeting_summary_failed"


class ReviewAgentError(MeetingIntelligenceError):
    code = "meeting_review_failed"


class AgentOutputValidationError(MeetingIntelligenceError):
    code = "meeting_agent_invalid_output"
    message = "Agent output failed evidence or contract validation"
    http_status = 502

    def __init__(self, reason="contract_invalid"):
        # Only fixed diagnostic codes, never model output or transcript text.
        allowed = {
            "contract_invalid",
            "empty_sources",
            "duplicate_sources",
            "unknown_sources",
            "no_target_evidence",
            "unknown_participant",
            "assignee_mismatch",
            "ambiguous_assignee",
            "deadline_kind_mismatch",
            "deadline_not_in_evidence",
            "relative_date_without_context",
            "unknown_review_entity",
        }
        self.reason = reason if reason in allowed else "contract_invalid"
        super().__init__()


class AgentConfigurationError(MeetingIntelligenceError):
    code = "meeting_intelligence_not_configured"
    message = "Enable meeting intelligence and configure all five models and OPENAI_API_KEY"


class AnalysisBudgetError(MeetingIntelligenceError):
    code = "meeting_analysis_budget_exceeded"
    message = "Analysis exceeds configured input budget; no partial analysis was saved"
    http_status = 422


class AnalysisBusyError(MeetingIntelligenceError):
    code = "meeting_analysis_busy"
    message = "Meeting analysis capacity is busy"
    http_status = 429


class AnalysisPersistenceError(MeetingIntelligenceError):
    code = "meeting_analysis_persistence_failed"


class SpeakerResolutionError(MeetingIntelligenceError):
    code = "speaker_resolution_failed"
    message = "Speaker resolution could not be completed"


class SpeakerResolutionValidationError(AgentOutputValidationError):
    code = "speaker_resolution_invalid_output"


class SpeakerResolutionConfigurationError(AgentConfigurationError):
    code = "speaker_resolution_not_configured"
    message = "Configure MEETING_SPEAKER_RESOLUTION_MODEL and OPENAI_API_KEY"
