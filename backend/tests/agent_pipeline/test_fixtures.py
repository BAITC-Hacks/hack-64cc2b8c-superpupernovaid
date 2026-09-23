"""Fixture integrity only. Semantic correctness is evaluated by opt-in real model tests."""

import json
from pathlib import Path

from app.canonicalization.models import CanonicalTranscriptSegment

SCENARIOS = json.loads((Path(__file__).parent / "fixtures/scenarios.json").read_text())


def test_evaluation_fixtures_cover_required_cases():
    assert len({s["name"] for s in SCENARIOS}) == 11
    for scenario in SCENARIOS:
        segments = [
            CanonicalTranscriptSegment(
                id=f"seg_{index:03}",
                start=index * 5,
                end=index * 5 + 4,
                speaker_id="SPEAKER_00",
                original_text=text,
                canonical_text=text,
            )
            for index, text in enumerate(scenario["segments"])
        ]
        assert segments and scenario["note"]
        assert scenario["expected_actions"] >= 0
