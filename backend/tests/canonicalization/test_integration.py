"""Explicit opt-in only: synthetic text, never meeting data or model downloads."""

import asyncio
import os

import pytest

from app.canonicalization.agent import OpenAITranscriptCanonicalizer
from app.canonicalization.batching import CanonicalizationBatch
from app.canonicalization.service import validate_batch
from app.config import Settings
from app.speech.models import AttributedTranscriptSegment

pytestmark = [pytest.mark.integration, pytest.mark.openai]


def test_real_structured_canonicalization_of_synthetic_sentence():
    if os.getenv("RUN_CANONICALIZATION_OPENAI_TESTS") != "1":
        pytest.skip("Explicit RUN_CANONICALIZATION_OPENAI_TESTS=1 required for paid API call")
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("TRANSCRIPT_CANONICALIZATION_MODEL"):
        pytest.fail("Export OPENAI_API_KEY and TRANSCRIPT_CANONICALIZATION_MODEL explicitly")
    settings = Settings(_env_file=None, transcript_canonical_language="ru")
    batch = CanonicalizationBatch(
        (
            AttributedTranscriptSegment(
                id="synthetic_segment",
                start=0,
                end=3,
                speaker_id="SPEAKER_00",
                text="Kubernetes-ті staging-ке deploy етіңіз.",
            ),
        )
    )

    async def run():
        adapter = OpenAITranscriptCanonicalizer(settings)
        try:
            result = await adapter.canonicalize_batch(batch)
            mapping = validate_batch(batch, result)
            text = mapping["synthetic_segment"].canonical_text
            assert "Kubernetes" in text and "staging" in text
        finally:
            await adapter.close()

    asyncio.run(run())
