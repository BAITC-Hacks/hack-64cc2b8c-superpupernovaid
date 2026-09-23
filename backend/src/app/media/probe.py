import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.media.errors import InvalidMediaError, MediaProbeError, UnsupportedMediaError
from app.media.models import MediaType
from app.media.validation import CHUNK_SIZE


@dataclass(frozen=True)
class MediaMetadata:
    media_type: MediaType
    container: str
    duration_seconds: float | None = None
    mime_type: str | None = None
    audio_codec: str | None = None
    video_codec: str | None = None


class MediaProbe(Protocol):
    def inspect(self, source: BinaryIO) -> MediaMetadata: ...


def parse_metadata(payload: dict) -> MediaMetadata:
    try:
        format_info = payload["format"]
        names = set(format_info["format_name"].split(","))
        container = next(
            (name for name in ("wav", "mp3", "flac", "ogg", "mov", "matroska") if name in names),
            None,
        )
        if container is None:
            raise UnsupportedMediaError
        streams = payload.get("streams", [])
        audio = next(
            (
                s
                for s in streams
                if s.get("codec_type") == "audio" and s.get("codec_name") not in {None, "unknown"}
            ),
            None,
        )
        video = next(
            (
                s
                for s in streams
                if s.get("codec_type") == "video"
                and s.get("codec_name") not in {None, "unknown"}
                and not s.get("disposition", {}).get("attached_pic", 0)
            ),
            None,
        )
        if audio is None and video is None:
            raise InvalidMediaError
        media_type = MediaType.VIDEO if video else MediaType.AUDIO
        duration = None
        for raw in [format_info.get("duration"), *(s.get("duration") for s in streams)]:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value >= 0:
                duration = max(duration or 0, value)
        mime = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "flac": "audio/flac",
            "ogg": f"{media_type}/ogg",
        }.get(container)
        # ffprobe groups MOV/MP4 and Matroska/WebM. Do not invent a MIME for an ambiguous family.
        if container == "mov":
            brand = format_info.get("tags", {}).get("major_brand", "").strip().lower()
            if brand == "qt":
                mime = "video/quicktime"
            elif brand in {"isom", "iso2", "mp41", "mp42", "m4a", "m4v", "avc1", "dash"}:
                mime = f"{media_type}/mp4"
        return MediaMetadata(
            media_type,
            container,
            duration,
            mime,
            audio.get("codec_name") if audio else None,
            video.get("codec_name") if video else None,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise InvalidMediaError from exc


class FFprobeMediaProbe:
    def __init__(self, timeout: float, executable: str = "ffprobe"):
        self.timeout, self.executable = timeout, executable

    def inspect(self, source: BinaryIO) -> MediaMetadata:
        # A seekable, private inspection copy also supports non-seekable S3 response streams.
        # No media bytes are passed on the command line or retained in RAM.
        try:
            with tempfile.TemporaryDirectory(prefix="media-probe-") as directory:
                path = Path(directory) / "source"
                with path.open("wb") as output:
                    shutil.copyfileobj(source, output, length=CHUNK_SIZE)
                with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                    completed = subprocess.run(
                        [
                            self.executable,
                            "-v",
                            "error",
                            "-protocol_whitelist",
                            "file",
                            "-format_whitelist",
                            "wav,mp3,flac,ogg,mov,matroska,webm",
                            "-max_alloc",
                            "67108864",
                            "-probesize",
                            "5000000",
                            "-analyzeduration",
                            "10000000",
                            "-show_entries",
                            "format=format_name,duration:format_tags=major_brand:"
                            "stream=codec_type,codec_name,duration:stream_disposition=attached_pic",
                            "-of",
                            "json",
                            "-i",
                            str(path),
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=stdout,
                        stderr=stderr,
                        timeout=self.timeout,
                        check=False,
                    )
                    if completed.returncode:
                        stderr.seek(0)
                        if b"not on whitelist" in stderr.read(8192):
                            raise UnsupportedMediaError
                        raise InvalidMediaError
                    if stdout.tell() > CHUNK_SIZE:
                        raise InvalidMediaError
                    stdout.seek(0)
                    try:
                        payload = json.load(stdout)
                    except (ValueError, UnicodeError) as exc:
                        raise InvalidMediaError from exc
                    return parse_metadata(payload)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MediaProbeError from exc
