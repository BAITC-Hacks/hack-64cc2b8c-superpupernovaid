import asyncio
import hashlib
import math
import shutil
import struct
import subprocess
import wave

import pytest

from app.audio.config import AudioProcessingConfig
from app.audio.ffmpeg import FfmpegAudioConverter
from app.audio.service import AudioPreprocessor
from app.media.probe import FFprobeMediaProbe

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_tools():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Requires real FFmpeg/ffprobe")


def store_source(path, storage, media):
    storage.delete(media.storage_key)
    with path.open("rb") as stream:
        storage.save(media.storage_key, iter(lambda: stream.read(1024 * 1024), b""), "audio/wav")


@pytest.mark.parametrize("extension", ["wav", "mp3", "m4a", "mp4"])
def test_real_conversion(extension, tmp_path, storage, repository, media, config):
    source = tmp_path / f"source.{extension}"
    args = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1:sample_rate=48000"]
    if extension == "mp4":
        args += ["-f", "lavfi", "-i", "color=s=16x16:r=5:d=1", "-c:v", "mpeg4"]
    args += ["-ac", "2", "-shortest", str(source)]
    subprocess.run(args, check=True, capture_output=True, timeout=20)
    store_source(source, storage, media)
    processor = AudioPreprocessor(
        storage, FfmpegAudioConverter(FFprobeMediaProbe(5), 10), repository, config
    )
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = asyncio.run(processor.process(media))
    with storage.open(result.storage_key) as output:
        metadata = FFprobeMediaProbe(5).inspect(output)
    assert (metadata.sample_rate, metadata.channels, metadata.audio_codec) == (
        16000,
        1,
        "pcm_s16le",
    )
    assert metadata.duration_seconds == pytest.approx(1, abs=0.07)
    with storage.open(media.storage_key) as original:
        assert hashlib.file_digest(original, "sha256").hexdigest() == before
    assert asyncio.run(processor.process(media)).id == result.id


def test_silence_not_trimmed_and_alternative_format(tmp_path, storage, repository, media):
    source = tmp_path / "silence.wav"
    with wave.open(str(source), "wb") as writer:
        writer.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        samples = []
        for index in range(72000):
            value = (
                int(10000 * math.sin(index / 48000 * 2 * math.pi * 440))
                if 24000 <= index < 48000
                else 0
            )
            samples.append(struct.pack("<hh", value, value))
        writer.writeframes(b"".join(samples))
    store_source(source, storage, media)
    for format, codec, rate, channels in [
        ("wav", "pcm_s16le", 16000, 1),
        ("flac", "flac", 48000, 2),
    ]:
        processor = AudioPreprocessor(
            storage,
            FfmpegAudioConverter(FFprobeMediaProbe(5), 10),
            repository,
            AudioProcessingConfig(sample_rate=rate, channels=channels, codec=codec, format=format),
        )
        result = asyncio.run(processor.process(media))
        assert result.duration_seconds == pytest.approx(1.5, abs=0.01)
        if format == "wav":
            with storage.open(result.storage_key) as output, wave.open(output, "rb") as audio:
                first = audio.readframes(7000)
                assert set(first) == {0}
                audio.setpos(17000)
                assert set(audio.readframes(7000)) == {0}


def test_video_audio_offset_preserved(tmp_path, storage, repository, media, config):
    source = tmp_path / "offset.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=16x16:r=10:d=1.5",
            "-itsoffset",
            "0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1:sample_rate=16000",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    store_source(source, storage, media)
    processor = AudioPreprocessor(
        storage, FfmpegAudioConverter(FFprobeMediaProbe(5), 10), repository, config
    )
    result = asyncio.run(processor.process(media))
    assert result.duration_seconds == pytest.approx(1.5, abs=0.01)
    with storage.open(result.storage_key) as output, wave.open(output, "rb") as audio:
        assert set(audio.readframes(7000)) == {0}
