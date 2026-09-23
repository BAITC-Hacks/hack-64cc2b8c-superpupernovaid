"""Explicit developer benchmark; no local user recording is a repository fixture."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.benchmark
def test_configured_real_meeting_pipeline(tmp_path):
    if os.getenv("RUN_MEETING_BENCHMARK") != "1":
        pytest.skip("Opt in with RUN_MEETING_BENCHMARK=1 and MEETING_BENCHMARK_AUDIO")
    audio = os.environ["MEETING_BENCHMARK_AUDIO"]
    completed = subprocess.run([
        sys.executable, "-m", "benchmarks.run_meeting", "--audio", audio,
        "--output", str(tmp_path / "results"),
        "--base-url", os.getenv("MEETING_BENCHMARK_API", "http://127.0.0.1:8000"),
        "--container", os.getenv("MEETING_BENCHMARK_CONTAINER", "superpupernova-backend-1"),
    ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=18000)
    reports = list((tmp_path / "results").glob("*/run_metadata.json"))
    assert len(reports) == 1
    metadata = json.loads(reports[0].read_text())
    assert completed.returncode == 0, metadata.get("error")
    assert metadata["status"] == "succeeded" and metadata["source_file_unchanged"]
    assert metadata["transcript_segments"] > 0
    assert (reports[0].parent / "attributed_transcript.json").exists()
    assert (reports[0].parent / "canonical_transcript.json").exists()
