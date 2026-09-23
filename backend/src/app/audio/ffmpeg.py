import logging
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import BinaryIO

from app.audio.config import AudioProcessingConfig
from app.audio.converter import ConvertedAudio
from app.audio.errors import (
    AudioConversionError,
    AudioProcessingTimeoutError,
    AudioStreamNotFoundError,
    AudioToolUnavailableError,
    NormalizedAudioStorageError,
    UnsupportedAudioError,
)
from app.media.errors import InvalidMediaError, MediaProbeError, UnsupportedMediaError
from app.media.probe import FFprobeMediaProbe
from app.media.validation import CHUNK_SIZE

logger = logging.getLogger(__name__)


def build_command(
    executable: str, source: Path, output: Path, config: AudioProcessingConfig
) -> list[str]:
    args = [
        executable,
        "-nostdin",
        "-hide_banner",
        "-v",
        "error",
        "-n",
        "-xerror",
        "-filter_threads",
        "1",
        "-max_alloc",
        "67108864",
        "-threads",
        "1",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        "wav,mp3,flac,ogg,mov,matroska,webm",
        "-copyts",
        "-start_at_zero",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        # Preserve silence and audio's offset relative to the recording timeline.
        "-af",
        f"aresample={config.sample_rate}:async=1:first_pts=0",
        "-ar",
        str(config.sample_rate),
        "-ac",
        str(config.channels),
        "-c:a",
        config.codec,
        "-f",
        config.format,
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-threads",
        "1",
    ]
    if config.format == "wav":
        args += ["-rf64", "auto"]  # Multi-hour PCM can exceed RIFF's 4 GiB size limit.
    return args + [str(output)]


class FfmpegAudioConverter:
    def __init__(self, probe: FFprobeMediaProbe, timeout: float, executable: str = "ffmpeg"):
        self.probe, self.timeout, self.executable = probe, timeout, executable

    def _inspect(self, path: Path):
        try:
            return self.probe.inspect_path(path)
        except UnsupportedMediaError as exc:
            raise UnsupportedAudioError from exc
        except InvalidMediaError as exc:
            raise AudioConversionError from exc
        except MediaProbeError as exc:
            if isinstance(exc.__cause__, subprocess.TimeoutExpired):
                raise AudioProcessingTimeoutError from exc
            raise AudioToolUnavailableError from exc

    def convert(
        self, source: BinaryIO, destination: BinaryIO, config: AudioProcessingConfig
    ) -> ConvertedAudio:
        try:
            with TemporaryDirectory(prefix="audio-convert-") as directory:
                input_path = Path(directory) / "source"
                output_path = Path(directory) / f"speech_input.{config.format}"
                with input_path.open("wb") as stream:
                    shutil.copyfileobj(source, stream, CHUNK_SIZE)
                info = self._inspect(input_path)
                if not info.audio_codec:
                    raise AudioStreamNotFoundError
                logger.info(
                    "audio_source codec=%s sample_rate=%s channels=%s duration=%s",
                    info.audio_codec,
                    info.sample_rate,
                    info.channels,
                    info.duration_seconds,
                )
                command = build_command(self.executable, input_path, output_path, config)
                with TemporaryFile() as stderr:
                    try:
                        completed = subprocess.run(
                            command,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=stderr,
                            timeout=self.timeout,
                            check=False,
                        )
                    except subprocess.TimeoutExpired as exc:
                        logger.warning("audio_ffmpeg_timeout timeout_seconds=%s", self.timeout)
                        raise AudioProcessingTimeoutError from exc
                    except FileNotFoundError as exc:
                        raise AudioToolUnavailableError from exc
                    if completed.returncode:
                        stderr.seek(0)
                        cause = subprocess.CalledProcessError(
                            completed.returncode, command, stderr=stderr.read(8192)
                        )
                        logger.warning("audio_ffmpeg_failed exit_code=%s", completed.returncode)
                        # stderr remains in the chained exception, not in logs or the HTTP response.
                        raise AudioConversionError from cause
                result = self._inspect(output_path)
                expected = (config.sample_rate, config.channels, config.codec, config.format)
                actual = (result.sample_rate, result.channels, result.audio_codec, result.container)
                if (
                    actual != expected
                    or not result.duration_seconds
                    or result.duration_seconds <= 0
                ):
                    raise AudioConversionError
                with output_path.open("rb") as stream:
                    shutil.copyfileobj(stream, destination, CHUNK_SIZE)
                return ConvertedAudio(*expected, result.duration_seconds)
        except OSError as exc:
            raise NormalizedAudioStorageError from exc
