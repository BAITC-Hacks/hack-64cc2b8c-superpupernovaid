from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.canonicalization.dependencies import canonicalization_profile
from app.canonicalization.models import CanonicalizationBatchResult, CanonicalizedSegmentOutput
from app.canonicalization.repository import CanonicalizationRepository
from app.canonicalization.service import TranscriptCanonicalizationService
from app.config import Settings
from app.infrastructure.database import Base
from app.speech.models import AttributedTranscript, AttributedTranscriptSegment

EXAMPLES = [
    ("Данияр, осы задачаны пятницаға дейін закройте.", "Данияр, закройте эту задачу до пятницы."),
    ("Ертең до обеда жіберіңіз.", "Отправьте завтра до обеда."),
    ("Kubernetes-ті staging-ке deploy етіңіз.", "Задеплойте Kubernetes в staging."),
    ("Может, Данияр потом посмотрит.", "Может быть, Данияр посмотрит это позже."),
]


class FakeCanonicalizer:
    def __init__(self):
        self.calls = []

    async def canonicalize_batch(self, batch):
        self.calls.append(batch)
        examples = dict(EXAMPLES)
        # Deliberately reverse output to exercise restoration of source order.
        return CanonicalizationBatchResult(
            segments=[
                CanonicalizedSegmentOutput(
                    id=s.id, canonical_text=examples.get(s.text, s.text), uncertain=False
                )
                for s in reversed(batch.targets)
            ]
        )


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        openai_api_key="unit-fake-key",
        transcript_canonicalization_model="configured-test-model",
        canonicalization_batch_max_segments=2,
        canonicalization_context_segments=1,
    )


@pytest.fixture
def transcript():
    return AttributedTranscript(
        source_audio_id=uuid4(),
        segments=[
            AttributedTranscriptSegment(
                id=f"seg_{i}",
                start=125.4 + i * 8,
                end=131.8 + i * 8,
                speaker_id="SPEAKER_01",
                text=text,
            )
            for i, (text, _) in enumerate(EXAMPLES)
        ],
    )


@pytest.fixture
def fake():
    return FakeCanonicalizer()


@pytest.fixture
def service(settings, engine, fake):
    return TranscriptCanonicalizationService(
        fake, settings, CanonicalizationRepository(engine), canonicalization_profile(settings)
    )
