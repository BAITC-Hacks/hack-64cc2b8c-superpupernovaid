import asyncio
from types import SimpleNamespace

import httpx
import pytest
from agents import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from openai import APIConnectionError, APIStatusError
from pydantic import SecretStr

from app.intelligence.pipeline import runner as module
from app.intelligence.pipeline.agents import SPECS
from app.intelligence.pipeline.dependencies import (
    intelligence_profile,
    validate_intelligence_configuration,
)
from app.intelligence.pipeline.errors import (
    AgentConfigurationError,
    AgentOutputValidationError,
    ExtractionAgentError,
)
from app.intelligence.pipeline.models import ChunkAnalysis, ExtractionInput
from app.intelligence.pipeline.runner import OpenAIMeetingAgents


def configured(settings):
    settings.openai_api_key = SecretStr("fake-unit-key")
    for stage in SPECS:
        setattr(settings, f"meeting_{stage}_model", f"configured-{stage}")
    return settings


def test_sdk_contracts_no_tools_and_private_trace(settings, monkeypatch):
    adapter = OpenAIMeetingAgents(configured(settings))
    result = ChunkAnalysis(
        action_items=[], decisions=[], important_facts=[], unresolved_references=[]
    )

    async def run(agent, **kwargs):
        assert agent.model.model == "configured-extraction"
        assert agent.output_type is ChunkAnalysis
        assert not agent.tools and not agent.handoffs
        assert agent.model_settings.store is False
        assert kwargs["max_turns"] == 1
        assert not kwargs["run_config"].trace_include_sensitive_data
        return SimpleNamespace(final_output=result)

    monkeypatch.setattr(module.Runner, "run", run)

    async def scenario():
        assert (
            await adapter.run("extraction", ExtractionInput(targets=[], context_only=[])) == result
        )
        await adapter.close()

    asyncio.run(scenario())
    assert len(adapter.agents) == 5 and adapter.client.max_retries == 0
    for _, contract in SPECS.values():
        assert AgentOutputSchema(contract).json_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
    "kind,retries",
    [(429, 3), (503, 3), (401, 1), (400, 1), ("timeout", 3), ("network", 3), ("schema", 1)],
)
def test_retries_and_sanitized_errors(settings, monkeypatch, caplog, kind, retries):
    adapter = OpenAIMeetingAgents(configured(settings))
    calls = []

    async def fail(*args, **kwargs):
        calls.append(1)
        if kind == "schema":
            raise ModelBehaviorError("private transcript")
        if kind == "timeout":
            raise TimeoutError("private transcript")
        request = httpx.Request("POST", "https://example.test")
        if kind == "network":
            raise APIConnectionError(request=request)
        raise APIStatusError(
            "private transcript", response=httpx.Response(kind, request=request), body=None
        )

    async def sleep(delay):
        pass

    monkeypatch.setattr(module.Runner, "run", fail)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)

    async def scenario():
        with pytest.raises(
            AgentOutputValidationError if kind == "schema" else ExtractionAgentError
        ) as error:
            await adapter.run("extraction", ExtractionInput(targets=[], context_only=[]))
        assert "private transcript" not in str(error.value)
        await adapter.close()

    asyncio.run(scenario())
    assert len(calls) == retries
    assert "private transcript" not in caplog.text


def test_opt_in_configuration_and_cache_profile(settings):
    validate_intelligence_configuration(settings)
    settings.meeting_intelligence_enabled = True
    with pytest.raises(AgentConfigurationError):
        validate_intelligence_configuration(settings)
    configured(settings)
    validate_intelligence_configuration(settings)
    before = intelligence_profile(settings)
    settings.openai_api_key = SecretStr("changed-key")
    assert intelligence_profile(settings) == before
    settings.meeting_review_model = "changed-model"
    assert intelligence_profile(settings) != before
