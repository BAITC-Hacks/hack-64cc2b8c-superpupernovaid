import asyncio
import json
import logging
import random
import time
from contextlib import nullcontext
from typing import Protocol

from agents import (
    Agent,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    Runner,
    set_tracing_export_api_key,
    trace,
)
from agents.exceptions import ModelBehaviorError
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.intelligence.pipeline.agents import COMMON, SPECS
from app.intelligence.pipeline.chunking import check_budget
from app.intelligence.pipeline.errors import (
    AgentOutputValidationError,
    ExtractionAgentError,
    ResolverAgentError,
    ReviewAgentError,
    SpeakerResolutionError,
    SpeakerResolutionValidationError,
    SummaryAgentError,
)
from app.intelligence.pipeline.output_schema import EvidenceOutputSchema
from app.intelligence.pipeline.validation import (
    target_findings,
    validate_extraction,
    validate_resolved,
    validate_review,
    validate_summary,
)

logger = logging.getLogger(__name__)
ERRORS = {
    "speaker_resolution": SpeakerResolutionError,
    "extraction": ExtractionAgentError,
    "resolver": ResolverAgentError,
    "summary": SummaryAgentError,
    "review": ReviewAgentError,
}


class AgentRunner(Protocol):
    async def run(self, stage: str, payload: BaseModel) -> BaseModel: ...

    def workflow(self, meeting_id: str): ...

    async def close(self): ...


class OpenAIMeetingAgents:
    def __init__(self, settings):
        self.settings = settings
        if settings.meeting_tracing_enabled:
            set_tracing_export_api_key(settings.openai_api_key.get_secret_value())
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.agent_timeout_seconds,
            max_retries=0,
        )
        self.agents = {
            stage: Agent(
                name="SpeakerResolutionAgent"
                if stage == "speaker_resolution"
                else f"Meeting{stage.title()}Agent",
                instructions=COMMON + module.INSTRUCTIONS,
                model=OpenAIResponsesModel(
                    model=getattr(settings, f"meeting_{stage}_model"),
                    openai_client=self.client,
                ),
                output_type=output,
                model_settings=ModelSettings(
                    store=False, max_tokens=settings.meeting_max_output_tokens
                ),
            )
            for stage, (module, output) in SPECS.items()
        }

    def workflow(self, meeting_id):
        if not self.settings.meeting_tracing_enabled:
            return nullcontext()
        return trace(
            workflow_name="meeting analysis",
            group_id=meeting_id,
            metadata={stage: module.VERSION for stage, (module, _) in SPECS.items()},
        )

    async def run(self, stage, payload):
        s = self.settings
        validation_error = (
            SpeakerResolutionValidationError
            if stage == "speaker_resolution"
            else AgentOutputValidationError
        )
        check_budget(payload, s.meeting_agent_max_input_bytes)
        agent = self.agents[stage].clone(output_type=EvidenceOutputSchema(SPECS[stage][1], payload))
        request_input = payload.model_dump_json()
        for attempt in range(s.meeting_agent_max_attempts):
            start = time.monotonic()
            result = None
            try:
                result = await asyncio.wait_for(
                    Runner.run(
                        agent,
                        input=request_input,
                        max_turns=1,
                        run_config=RunConfig(
                            tracing_disabled=not s.meeting_tracing_enabled,
                            trace_include_sensitive_data=False,
                        ),
                    ),
                    timeout=s.agent_timeout_seconds,
                )
                if not isinstance(result.final_output, SPECS[stage][1]):
                    raise validation_error
                output = result.final_output
                if stage == "extraction":
                    output = target_findings(output, payload)
                    validate_extraction(output, payload)
                elif stage == "resolver":
                    validate_resolved(
                        result.final_output, payload, {s.id for s in payload.evidence}
                    )
                elif stage == "summary":
                    validate_summary(result.final_output, {s.id for s in payload.evidence})
                elif stage == "review":
                    validate_review(result.final_output, payload)
                logger.info(
                    "meeting_agent_done stage=%s model=%s duration=%.3f",
                    stage,
                    getattr(s, f"meeting_{stage}_model"),
                    time.monotonic() - start,
                )
                return output
            except AgentOutputValidationError as exc:
                if stage == "speaker_resolution" or attempt + 1 == s.meeting_agent_max_attempts:
                    logger.warning("meeting_agent_invalid stage=%s reason=%s", stage, exc.reason)
                    raise
                logger.warning("meeting_agent_retry stage=%s reason=%s", stage, exc.reason)
                rejected = getattr(result, "final_output", None)
                correction = json.dumps(
                    {
                        "input": payload.model_dump(mode="json"),
                        "rejected_response": rejected.model_dump(mode="json")
                        if isinstance(rejected, SPECS[stage][1]) else None,
                        "validation_error": exc.reason,
                    }, ensure_ascii=False,
                )
                # Feedback is also bounded; never silently expand the input budget.
                if len(correction.encode("utf-8")) <= s.meeting_agent_max_input_bytes:
                    request_input = correction
                agent = agent.clone(instructions=self.agents[stage].instructions + (
                    "\nA previous attempt failed evidence validation: " + exc.reason + ". "
                    "Rebuild your response from supplied evidence. Copy IDs exactly, without "
                    "duplicates. Use null for unknown participants and copy known names exactly. "
                    "For extraction every finding must cite an actual target ID: omit findings "
                    "supported only by context_only; never add unrelated citations to pass. "
                    "For resolver copy deadline_text as an EXACT contiguous substring from the "
                    "cited original/canonical segments joined in transcript order. Cite ALL "
                    "segments containing the deadline phrase, including short word fragments. "
                    "Never paraphrase a deadline quote. If none is supported use null deadline, "
                    "null deadline_text and unspecified kind. Without meeting timezone AND date, "
                    "relative deadlines must have null normalized date and needs_review=true. "
                    "Review issues must reference a supplied entity and its own evidence."
                ))
            except (ModelBehaviorError, ValidationError) as exc:
                logger.warning(
                    "meeting_agent_contract_invalid stage=%s kind=%s", stage, type(exc).__name__
                )
                raise validation_error from exc
            except (TimeoutError, APIConnectionError, APIStatusError) as exc:
                transient = isinstance(exc, (TimeoutError, APIConnectionError)) or (
                    isinstance(exc, APIStatusError)
                    and (exc.status_code == 429 or 500 <= exc.status_code < 600)
                )
                if not transient or attempt + 1 == s.meeting_agent_max_attempts:
                    raise ERRORS[stage] from exc
                delay = min(8, s.meeting_agent_retry_base_seconds * 2**attempt)
                await asyncio.sleep(delay + random.uniform(0, delay / 4))
            except Exception as exc:
                raise ERRORS[stage] from exc
        raise ERRORS[stage]

    async def close(self):
        await self.client.close()
