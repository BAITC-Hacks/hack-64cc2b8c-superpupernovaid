import shutil
import subprocess

import pytest

from app.media.errors import InvalidMediaError, UnsupportedMediaError
from app.media.probe import FFprobeMediaProbe

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def need_ffprobe():
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        pytest.skip("Real-media integration tests require ffprobe and ffmpeg")


@pytest.mark.parametrize(
    "extension,audio_codec,video_codec,kind,container",
    [
        ("wav", "pcm_s16le", None, "audio", "wav"),
        ("mp3", "libmp3lame", None, "audio", "mp3"),
        ("flac", "flac", None, "audio", "flac"),
        ("ogg", "libopus", None, "audio", "ogg"),
        ("m4a", "aac", None, "audio", "mov"),
        ("mp4", "aac", "mpeg4", "video", "mov"),
        ("mov", "aac", "mpeg4", "video", "mov"),
        ("mkv", "aac", "mpeg4", "video", "matroska"),
        ("webm", "libopus", "libvpx-vp9", "video", "matroska"),
    ],
)
def test_real_upload(
    client,
    service,
    repository,
    storage,
    meeting_id,
    tmp_path,
    extension,
    audio_codec,
    video_codec,
    kind,
    container,
):
    service.probe = FFprobeMediaProbe(10)
    path = tmp_path / f"generated.{extension}"
    args = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2"]
    if video_codec:
        args += ["-f", "lavfi", "-i", "color=c=blue:s=16x16:r=5:d=0.2", "-c:v", video_codec]
    args += ["-c:a", audio_codec, "-shortest", str(path)]
    subprocess.run(args, check=True, timeout=20, capture_output=True)
    with path.open("rb") as upload:
        response = client.post(
            f"/api/v1/meetings/{meeting_id}/media",
            files={"file": ("misleading.txt", upload, "text/plain")},
        )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["media_type"] == kind and asset["container"] == container
    assert asset["audio_codec"] and asset["duration_seconds"] > 0
    if kind == "video":
        assert asset["video_codec"]
    with storage.open(asset["storage_key"]) as original:
        assert original.read() == path.read_bytes()


def test_real_corrupt_and_unsupported(tmp_path):
    from io import BytesIO

    probe = FFprobeMediaProbe(10)
    with pytest.raises(InvalidMediaError):
        probe.inspect(BytesIO(b"RIFF fake corrupted WAV file"))
    # A real PNG is a valid image, but not accepted meeting media.
    image = tmp_path / "image.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=16x16",
            "-frames:v",
            "1",
            str(image),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    with image.open("rb") as stream, pytest.raises(UnsupportedMediaError):
        probe.inspect(stream)
