import json
import subprocess
from io import BytesIO
from types import SimpleNamespace

import pytest

from app.media.errors import InvalidMediaError, MediaProbeError, UnsupportedMediaError
from app.media.probe import FFprobeMediaProbe, parse_metadata


def payload(streams, duration="12.5", format_name="mov,mp4,m4a,3gp,3g2,mj2"):
    return {"format": {"format_name": format_name, "duration": duration}, "streams": streams}


def test_video_and_audio_streams():
    result = parse_metadata(
        payload(
            [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        )
    )
    assert result.media_type == "video"
    assert result.audio_codec == "aac" and result.video_codec == "h264"
    assert result.duration_seconds == 12.5
    assert result.mime_type is None


def test_cover_art_does_not_make_audio_a_video():
    result = parse_metadata(
        payload(
            [
                {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
                {"codec_type": "audio", "codec_name": "mp3"},
            ],
            format_name="mp3",
        )
    )
    assert result.media_type == "audio" and result.video_codec is None


@pytest.mark.parametrize("duration", [None, "N/A", "NaN", "inf", "-5"])
def test_unknown_duration_is_nullable(duration):
    result = parse_metadata(payload([{"codec_type": "audio", "codec_name": "aac"}], duration))
    assert result.duration_seconds is None


@pytest.mark.parametrize(
    "data,error",
    [
        ({}, InvalidMediaError),
        (payload([]), InvalidMediaError),
        (payload([{"codec_type": "subtitle", "codec_name": "ass"}]), InvalidMediaError),
        (payload([{"codec_type": "audio", "codec_name": "unknown"}]), InvalidMediaError),
        (payload([], format_name="gif"), UnsupportedMediaError),
    ],
)
def test_bad_metadata(data, error):
    with pytest.raises(error):
        parse_metadata(data)


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), OSError(), subprocess.TimeoutExpired("ffprobe", 1)]
)
def test_probe_failure_is_controlled(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(MediaProbeError):
        FFprobeMediaProbe(1).inspect(BytesIO(b"input"))


def test_subprocess_arguments_and_output(monkeypatch):
    def run(args, **kwargs):
        assert args[0] == "ffprobe"
        assert args[args.index("-protocol_whitelist") + 1] == "file"
        assert kwargs["timeout"] == 2
        assert not kwargs.get("shell", False)
        data = payload([{"codec_type": "audio", "codec_name": "pcm_s16le"}], format_name="wav")
        kwargs["stdout"].write(json.dumps(data).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert FFprobeMediaProbe(2).inspect(BytesIO(b"input")).media_type == "audio"


def test_invalid_ffprobe_json(monkeypatch):
    def run(args, **kwargs):
        kwargs["stdout"].write(b"not JSON")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(InvalidMediaError):
        FFprobeMediaProbe(1).inspect(BytesIO(b"input"))
