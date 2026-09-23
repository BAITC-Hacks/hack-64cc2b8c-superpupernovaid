"""Replay the production HTTP pipeline; never synthesize speech or bypass its services."""

import argparse
import hashlib
import json
import resource
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from app.audio.models import NormalizedAudioResponse
from app.canonicalization.models import CanonicalTranscript
from app.canonicalization.service import validate_metadata
from app.media.models import MediaAssetResponse
from app.speech.models import AttributedTranscript

SERVER_CONFIG = """
import importlib.metadata,json
from pathlib import Path
from app.config import get_settings
s=get_settings()
fields=['speech_enabled','asr_provider','diarization_provider','nemo_asr_model',
'nemo_diarization_model','nemo_device','whisper_model','whisper_device','pyannote_model',
'pyannote_device','transcript_canonicalization_enabled','transcript_canonicalization_model',
'transcript_canonical_language','audio_target_sample_rate','audio_target_channels',
'audio_target_codec','audio_target_format','speech_model_revision']
result={key:getattr(s,key) for key in fields}
result['openai_key_configured']=bool(s.openai_api_key.get_secret_value())
result['local_models_exist']={key:bool(getattr(s,key)) and Path(getattr(s,key)).exists()
for key in ['nemo_asr_model','nemo_diarization_model','whisper_model','pyannote_model']}
result['packages']={}
for package in ['nemo_toolkit','torch','faster-whisper','pyannote.audio']:
 try:result['packages'][package]=importlib.metadata.version(package)
 except importlib.metadata.PackageNotFoundError:result['packages'][package]=None
print(json.dumps(result))
"""
RSS_SCRIPT = """
import os,json
from pathlib import Path
rss=0
for proc in Path('/proc').glob('[0-9]*'):
 if proc.name==str(os.getpid()):continue
 try:
  for line in (proc/'status').read_text().splitlines():
   if line.startswith('VmRSS:'):rss+=int(line.split()[1])*1024
 except (OSError,ValueError):pass
print(json.dumps({'rss_bytes':rss}))
"""
ARTIFACT_SCRIPT = """
import sys,json,hashlib
from dataclasses import asdict
from pathlib import Path
from app.config import get_settings
from app.bootstrap import get_media_storage
from app.media.probe import FFprobeMediaProbe
s=get_settings();store=get_media_storage();result={}
for label,key in zip(['source','normalized'],sys.argv[1:]):
 digest=hashlib.sha256();size=0
 with store.open(key) as stream:
  while chunk:=stream.read(1024*1024):digest.update(chunk);size+=len(chunk)
 result[label]={'storage_key':key,'sha256':digest.hexdigest(),'size_bytes':size,
 'path':str(s.media_upload_dir/key)}
result['normalized']['probe']=asdict(FFprobeMediaProbe(
 s.media_ffprobe_timeout_seconds,s.media_ffprobe_executable).inspect_path(
 Path(result['normalized']['path'])))
print(json.dumps(result))
"""


def docker_json(container, script, *args):
    completed = subprocess.run(
        ["docker", "exec", container, "python", "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(completed.stdout)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_source(path):
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size:stream=index,codec_type,codec_name,sample_rate,channels:"
            "stream_disposition=attached_pic",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


class RssSampler:
    def __init__(self, container):
        self.container = container
        self.samples = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def sample(self):
        sample = {"elapsed_seconds": round(time.monotonic() - self.started, 3)}
        sample["client_high_water_rss_bytes"] = resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        try:
            if self.container:
                sample["backend_processes_rss_bytes"] = docker_json(self.container, RSS_SCRIPT)[
                    "rss_bytes"
                ]
        except (OSError, ValueError, subprocess.SubprocessError):
            sample["backend_sample_unavailable"] = True
        self.samples.append(sample)

    def _run(self):
        while not self.stop_event.wait(0.2):
            self.sample()

    def __enter__(self):
        self.started = time.monotonic()
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop_event.set()
        self.thread.join(timeout=35)
        self.sample()

    def report(self):
        result = {
            "sample_count": len(self.samples),
            "samples": self.samples,
            "method": "Approximate 0.2s sampling; sum of backend process RSS excludes sampler. "
            "Shared pages may be counted twice; brief peaks can be missed. "
            "Client metric is process-lifetime high-water RSS, not current RSS.",
        }
        for key in ["client_high_water_rss_bytes", "backend_processes_rss_bytes"]:
            values = [s[key] for s in self.samples if key in s]
            result[key] = (
                {"before": values[0], "approx_peak": max(values), "after": values[-1]}
                if values
                else None
            )
        return result


class StageFailure(Exception):
    def __init__(self, stage, status, code):
        self.stage, self.status, self.code = stage, status, code
        super().__init__(f"{stage}: HTTP {status}, {code}")


def checked(response, stage):
    if response.is_error:
        code = "http_error"
        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict):
                code = detail.get("code", code)
        except ValueError:
            pass
        raise StageFailure(stage, response.status_code, code)
    return response.json()


def validate_attributed(transcript):
    if not transcript.segments:
        raise ValueError("Empty attributed transcript")
    if len({s.id for s in transcript.segments}) != len(transcript.segments):
        raise ValueError("Duplicate segment IDs")
    starts = [s.start for s in transcript.segments]
    if starts != sorted(starts) or any(
        not s.id or not s.speaker_id or not s.text for s in transcript.segments
    ):
        raise ValueError("Invalid transcript ordering or content")


def run(args):
    source = Path(args.audio).resolve(strict=True)
    started = time.monotonic()
    folder = Path(args.output).resolve() / datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    before_hash = sha256_file(source)
    metadata = {
        "source_file": str(source),
        "source_sha256": before_hash,
        "result_directory": str(folder),
        "meeting_id": str(args.meeting_id or uuid4()),
        "media_id": None,
        "preprocessing_seconds": None,
        "speech_processing_seconds": None,
        "canonicalization_seconds": None,
        "detected_speakers": None,
        "transcript_segments": None,
        "stages": {},
        "status": "running",
    }
    stage = "inspection"
    sampler = RssSampler(args.container)
    try:
        metadata["source_probe"] = inspect_source(source)
        metadata["audio_duration_seconds"] = float(metadata["source_probe"]["format"]["duration"])
        save_json(folder / "source_probe.json", metadata["source_probe"])
        metadata["stages"][stage] = "ok"
        if args.container:
            config = docker_json(args.container, SERVER_CONFIG)
            metadata["server_configuration"] = config
            metadata.update(
                {
                    "asr_provider": config["asr_provider"],
                    "diarization_provider": config["diarization_provider"],
                    "asr_model": config["nemo_asr_model"]
                    if config["asr_provider"] == "nemo"
                    else config["whisper_model"],
                    "diarization_model": config["nemo_diarization_model"]
                    if config["diarization_provider"] == "nemo"
                    else config["pyannote_model"],
                    "canonicalization_model": config["transcript_canonicalization_model"],
                }
            )
        with sampler, httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
            stage = "ingestion"
            root = f"/api/v1/meetings/{metadata['meeting_id']}/media"
            call_start = time.monotonic()
            if args.media_id:
                media = MediaAssetResponse.model_validate(
                    checked(client.get(root + "/" + str(args.media_id)), stage)
                )
                metadata["ingestion_mode"] = "reused_existing_media"
            else:
                # httpx streams multipart from the file object in bounded chunks.
                with source.open("rb") as stream:
                    media = MediaAssetResponse.model_validate(
                        checked(
                            client.post(root, files={"file": (source.name, stream, "audio/mpeg")}),
                            stage,
                        )
                    )
                metadata["ingestion_mode"] = "streaming_upload"
            metadata["ingestion_seconds"] = time.monotonic() - call_start
            metadata["media_id"] = str(media.id)
            metadata["stages"][stage] = "ok"
            save_json(folder / "media_asset.json", media.model_dump(mode="json"))
            save_json(folder / "run_metadata.json", metadata)
            endpoint = root + "/" + str(media.id)
            stage = "preprocessing"
            call_start = time.monotonic()
            audio = NormalizedAudioResponse.model_validate(
                checked(client.post(endpoint + "/preprocess"), stage)
            )
            metadata["preprocessing_seconds"] = time.monotonic() - call_start
            unchanged = MediaAssetResponse.model_validate(checked(client.get(endpoint), stage))
            if (
                unchanged != media
                or audio.source_media_id != media.id
                or audio.storage_key == media.storage_key
            ):
                raise ValueError("Original/derived artifact identity mismatch")
            if abs(audio.duration_seconds - metadata["audio_duration_seconds"]) > 0.1:
                raise ValueError("Preprocessing duration changed by more than 100 ms")
            if args.container:
                if (audio.sample_rate, audio.channels, audio.codec, audio.format) != (
                    config["audio_target_sample_rate"],
                    config["audio_target_channels"],
                    config["audio_target_codec"],
                    config["audio_target_format"],
                ):
                    raise ValueError("Normalization profile mismatch")
                artifacts = docker_json(
                    args.container, ARTIFACT_SCRIPT, media.storage_key, audio.storage_key
                )
                if (
                    artifacts["source"]["sha256"] != before_hash
                    or artifacts["normalized"]["sha256"] != audio.sha256
                ):
                    raise ValueError("Stored artifact checksum mismatch")
                probe = artifacts["normalized"]["probe"]
                if (probe["sample_rate"], probe["channels"], probe["audio_codec"]) != (
                    audio.sample_rate,
                    audio.channels,
                    audio.codec,
                ):
                    raise ValueError("Actual normalized file does not match metadata")
                metadata["artifacts"] = artifacts
            metadata["normalized_audio_id"] = str(audio.id)
            metadata["stages"][stage] = "ok"
            save_json(folder / "normalized_audio.json", audio.model_dump(mode="json"))
            save_json(folder / "run_metadata.json", metadata)
            stage = "speech"
            call_start = time.monotonic()
            try:
                transcript = AttributedTranscript.model_validate(
                    checked(client.post(endpoint + "/speech"), stage)
                )
            finally:
                metadata["speech_processing_seconds"] = time.monotonic() - call_start
            validate_attributed(transcript)
            if transcript.source_audio_id != audio.id:
                raise ValueError("Speech source audio mismatch")
            metadata["detected_speakers"] = len(
                {s.speaker_id for s in transcript.segments} - {"UNKNOWN"}
            )
            metadata["transcript_segments"] = len(transcript.segments)
            metadata["transcript_duration_seconds"] = max(s.end for s in transcript.segments)
            metadata["stages"][stage] = "ok"
            save_json(folder / "attributed_transcript.json", transcript.model_dump(mode="json"))
            save_json(folder / "run_metadata.json", metadata)
            stage = "canonicalization"
            call_start = time.monotonic()
            try:
                canonical = CanonicalTranscript.model_validate(
                    checked(client.post(endpoint + "/canonicalize"), stage)
                )
            finally:
                metadata["canonicalization_seconds"] = time.monotonic() - call_start
            validate_metadata(
                transcript,
                canonical,
                config["transcript_canonical_language"]
                if args.container
                else canonical.canonical_language,
            )
            metadata["stages"][stage] = "ok"
            save_json(folder / "canonical_transcript.json", canonical.model_dump(mode="json"))
            metadata["status"] = "succeeded"
    except StageFailure as exc:
        metadata["status"] = "blocked"
        metadata["stages"][stage] = "blocked"
        metadata["error"] = {"stage": exc.stage, "http_status": exc.status, "code": exc.code}
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["stages"][stage] = "failed"
        # Do not serialize native exception text or HTTP request/headers.
        metadata["error"] = {"stage": stage, "type": type(exc).__name__}
    finally:
        metadata["source_file_unchanged"] = sha256_file(source) == before_hash
        if not metadata["source_file_unchanged"]:
            metadata["status"] = "failed"
        metadata["memory"] = sampler.report()
        metadata["total_processing_seconds"] = time.monotonic() - started
        save_json(folder / "run_metadata.json", metadata)
    print(
        json.dumps(
            {
                k: metadata.get(k)
                for k in [
                    "status",
                    "stages",
                    "meeting_id",
                    "media_id",
                    "normalized_audio_id",
                    "detected_speakers",
                    "transcript_segments",
                    "error",
                    "source_file_unchanged",
                    "result_directory",
                    "total_processing_seconds",
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if metadata["status"] == "succeeded" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", default="benchmarks/results/meeting")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--container",
        default="superpupernova-backend-1",
        help="Local backend container for configuration/artifact/RSS inspection; empty disables",
    )
    parser.add_argument("--meeting-id", type=UUID)
    parser.add_argument(
        "--media-id", type=UUID, help="Reuse an uploaded source; requires --meeting-id"
    )
    parser.add_argument("--timeout", type=float, default=14400)
    args = parser.parse_args()
    if args.media_id and not args.meeting_id:
        parser.error("--media-id requires --meeting-id")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
