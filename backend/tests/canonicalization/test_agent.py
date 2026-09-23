import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from agents import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from openai import APIConnectionError, APIStatusError

from app.canonicalization import agent as module
from app.canonicalization.agent import OpenAITranscriptCanonicalizer
from app.canonicalization.batching import CanonicalizationBatch
from app.canonicalization.dependencies import (
    canonicalization_profile,
    validate_canonicalization_configuration,
)
from app.canonicalization.errors import (
    CanonicalizationConfigurationError,
    CanonicalizationProviderError,
    CanonicalizationValidationError,
)
from app.canonicalization.models import CanonicalizationBatchResult, CanonicalizedSegmentOutput
from app.config import Settings


def output(batch):
    return SimpleNamespace(
        final_output=CanonicalizationBatchResult(
            segments=[
                CanonicalizedSegmentOutput(id=s.id, canonical_text=s.text, uncertain=False)
                for s in batch.targets
            ]
        )
    )


def test_sdk_single_agent_structured_output_no_tools_tracing_or_storage(
    settings, transcript, monkeypatch
):
    adapter = OpenAITranscriptCanonicalizer(settings)
    batch = CanonicalizationBatch(tuple(transcript.segments))

    async def run(agent, payload, **kwargs):
        assert agent.name == "TranscriptCanonicalizerAgent"
        assert agent.tools == [] and agent.handoffs == []
        assert agent.model.model == "configured-test-model"
        assert agent.output_type is CanonicalizationBatchResult
        assert agent.model_settings.store is False
        assert kwargs["max_turns"] == 1
        assert kwargs["run_config"].tracing_disabled
        assert not kwargs["run_config"].trace_include_sensitive_data
        decoded = json.loads(payload)
        assert decoded["canonical_language"] == "ru"
        assert set(decoded["targets"][0]) == {"id", "text"}
        assert "unit-fake-key" not in payload
        return output(batch)

    monkeypatch.setattr(module.Runner, "run", run)

    async def check():
        assert await adapter.canonicalize_batch(batch) == output(batch).final_output
        await adapter.close()

    asyncio.run(check())
    schema = AgentOutputSchema(CanonicalizationBatchResult).json_schema()
    assert schema["additionalProperties"] is False
    assert "original_text" not in json.dumps(schema)


@pytest.mark.parametrize(
    "kind,retry",
    [
        (429, True),
        (500, True),
        (503, True),
        (401, False),
        (400, False),
        ("timeout", True),
        ("network", True),
    ],
)
def test_bounded_transient_retry_only(settings, transcript, monkeypatch, caplog, kind, retry):
    adapter = OpenAITranscriptCanonicalizer(settings)
    batch = CanonicalizationBatch(tuple(transcript.segments))
    calls, sleeps = [], []

    async def fail(*args, **kwargs):
        calls.append(1)
        if kind == "timeout":
            raise TimeoutError("secret transcript")
        if kind == "network":
            raise APIConnectionError(request=httpx.Request("POST", "https://example.test"))
        response = httpx.Response(kind, request=httpx.Request("POST", "https://example.test"))
        raise APIStatusError("secret transcript unit-fake-key", response=response, body=None)

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(module.Runner, "run", fail)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)

    async def check():
        try:
            with pytest.raises(CanonicalizationProviderError) as error:
                await adapter.canonicalize_batch(batch)
            assert "secret" not in str(error.value)
        finally:
            await adapter.close()

    asyncio.run(check())
    assert len(calls) == (3 if retry else 1)
    assert len(sleeps) == (2 if retry else 0)
    assert "secret transcript" not in caplog.text and "unit-fake-key" not in caplog.text
    assert adapter.client.max_retries == 0


@pytest.mark.parametrize("bad", ["wrong_output", "invalid_json"])
def test_invalid_provider_output_not_retried(settings, transcript, monkeypatch, bad):
    adapter = OpenAITranscriptCanonicalizer(settings)
    calls = []

    async def invalid(*a, **kw):
        calls.append(1)
        if bad == "invalid_json":
            raise ModelBehaviorError("sensitive invalid output")
        return SimpleNamespace(final_output="not a typed model")

    monkeypatch.setattr(module.Runner, "run", invalid)

    async def check():
        try:
            with pytest.raises(CanonicalizationValidationError):
                await adapter.canonicalize_batch(CanonicalizationBatch(tuple(transcript.segments)))
        finally:
            await adapter.close()

    asyncio.run(check())
    assert calls == [1]


def test_configuration_opt_in_and_existing_secret(settings):
    validate_canonicalization_configuration(Settings(_env_file=None, openai_api_key=""))
    for kwargs in [
        dict(openai_api_key="", transcript_canonicalization_model="test"),
        dict(openai_api_key="not-real", transcript_canonicalization_model=""),
    ]:
        with pytest.raises(CanonicalizationConfigurationError):
            validate_canonicalization_configuration(
                Settings(_env_file=None, transcript_canonicalization_enabled=True, **kwargs)
            )
    settings.transcript_canonicalization_enabled = True
    validate_canonicalization_configuration(settings)
    before = canonicalization_profile(settings)
    settings.openai_api_key = "some-other-secret"
    assert canonicalization_profile(settings) == before
    settings.transcript_canonical_language = "kk"
    assert canonicalization_profile(settings) != before
