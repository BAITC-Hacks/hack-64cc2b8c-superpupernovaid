import subprocess
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.audio.config import AudioProcessingConfig
from app.audio.errors import (
    AudioConversionError,
    AudioProcessingTimeoutError,
    AudioToolUnavailableError,
)
from app.audio.ffmpeg import FfmpegAudioConverter, build_command
from app.media.probe import MediaMetadata


def test_command_uses_config_and_preserves_timeline(config):
    command = build_command("ffmpeg", Path("/tmp/source"), Path("/tmp/out"), config)
    for flag, expected in [
        ("-map", "0:a:0"),
        ("-ar", "16000"),
        ("-ac", "1"),
        ("-c:a", "pcm_s16le"),
        ("-f", "wav"),
        ("-rf64", "auto"),
    ]:
        assert command[command.index(flag) + 1] == expected
    assert "-copyts" in command and "-start_at_zero" in command
    assert not any(word in " ".join(command) for word in ["silenceremove", "denoise", "afftdn"])


@pytest.mark.parametrize(
    "format,codec", [("wav", "flac"), ("flac", "pcm_s16le"), ("mp3", "libmp3lame")]
)
def test_invalid_settings(format, codec):
    with pytest.raises(ValueError):
        AudioProcessingConfig(sample_rate=16000, channels=1, codec=codec, format=format)


@pytest.mark.parametrize(
    "failure,error",
    [
        (subprocess.TimeoutExpired("ffmpeg", 1), AudioProcessingTimeoutError),
        (FileNotFoundError(), AudioToolUnavailableError),
        (None, AudioConversionError),
    ],
)
def test_ffmpeg_failures_are_controlled(config, monkeypatch, failure, error, caplog):
    probe = Mock()
    probe.inspect_path.return_value = MediaMetadata(
        "audio", "wav", 1, "audio/wav", "pcm_s16le", None, 16000, 1
    )

    def run(args, **kwargs):
        assert not kwargs.get("shell", False)
        if failure:
            raise failure
        kwargs["stderr"].write(b"private path and sensitive metadata")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(error) as result:
        FfmpegAudioConverter(probe, 1).convert(BytesIO(b"input"), BytesIO(), config)
    assert result.value.__cause__ is not None
    assert "private path" not in caplog.text


def test_output_is_inspected(config, monkeypatch):
    probe = Mock()
    info = MediaMetadata("audio", "wav", 1, "audio/wav", "pcm_s16le", None, 16000, 1)
    probe.inspect_path.side_effect = [info, replace(info, sample_rate=48000)]
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    with pytest.raises(AudioConversionError):
        FfmpegAudioConverter(probe, 1).convert(BytesIO(b"input"), BytesIO(), config)
