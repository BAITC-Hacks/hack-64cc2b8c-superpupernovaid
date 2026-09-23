import asyncio
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
        for attempt in range(s.meeting_agent_max_attempts):
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    Runner.run(
                        self.agents[stage],
                        input=payload.model_dump_json(),
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
                logger.info(
                    "meeting_agent_done stage=%s model=%s duration=%.3f",
                    stage,
                    getattr(s, f"meeting_{stage}_model"),
                    time.monotonic() - start,
                )
                return result.final_output
            except AgentOutputValidationError:
                raise
            except (ModelBehaviorError, ValidationError) as exc:
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
