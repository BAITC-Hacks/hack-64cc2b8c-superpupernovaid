import asyncio
import json
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
        assert agent.output_type.output_type is ChunkAnalysis
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


@pytest.mark.parametrize("recover", [True, False])
def test_unknown_evidence_retry_is_bounded(settings, meeting_input, monkeypatch, recover):
    from app.intelligence.pipeline.models import GroundedText

    adapter = OpenAIMeetingAgents(configured(settings))
    segments = meeting_input.transcript.segments
    payload = ExtractionInput(targets=[segments[1]], context_only=[segments[0]])
    calls = []

    async def run(agent, **kwargs):
        calls.append(agent.instructions)
        ids = [segments[1].id] if recover and len(calls) > 1 else ["unknown-id"]
        return SimpleNamespace(final_output=ChunkAnalysis(
            action_items=[], decisions=[], unresolved_references=[],
            important_facts=[GroundedText(text="Fact", source_segment_ids=ids)],
        ))

    monkeypatch.setattr(module.Runner, "run", run)

    async def scenario():
        if recover:
            result = await adapter.run("extraction", payload)
            assert result.important_facts[0].source_segment_ids == [segments[1].id]
        else:
            with pytest.raises(AgentOutputValidationError, match="contract validation"):
                await adapter.run("extraction", payload)
        await adapter.close()

    asyncio.run(scenario())
    assert len(calls) == (2 if recover else settings.meeting_agent_max_attempts)
    assert "unknown_sources" in calls[1]
    assert "unknown_sources" not in adapter.agents["extraction"].instructions


def test_resolver_retries_invalid_deadline_evidence(settings, meeting_input, fake, monkeypatch):
    from app.intelligence.pipeline.models import ResolverInput

    adapter = OpenAIMeetingAgents(configured(settings))
    payload = ResolverInput(
        meeting=meeting_input.meeting, participants=meeting_input.participants,
        speaker_mapping=[], chunks=[], evidence=meeting_input.transcript.segments,
    )
    calls = []

    async def run(agent, **kwargs):
        calls.append(agent.instructions)
        result = fake.resolved.model_copy(deep=True)
        if len(calls) == 1:
            result.action_items[0].deadline_text = "несуществующий срок"
        else:
            correction = json.loads(kwargs["input"])
            assert correction["validation_error"] == "deadline_not_in_evidence"
            assert correction["rejected_response"]["action_items"][0]["deadline_text"] == (
                "несуществующий срок"
            )
            assert correction["input"] == payload.model_dump(mode="json")
        return SimpleNamespace(final_output=result)

    monkeypatch.setattr(module.Runner, "run", run)

    async def scenario():
        result = await adapter.run("resolver", payload)
        assert result.action_items[0].deadline_text == "до пятницы"
        await adapter.close()

    asyncio.run(scenario())
    assert len(calls) == 2
    assert "deadline_not_in_evidence" in calls[1]
