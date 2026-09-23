"""NVIDIA hosted Riva: one bounded request shared by ASR and diarization."""

import asyncio
from threading import Lock

from app.speech.errors import SpeechCloudAudioTooLarge, SpeechCloudError, SpeechRecognitionError
from app.speech.models import (
    DiarizationResult,
    SpeakerSegment,
    TranscriptionResult,
    TranscriptionSegment,
)


def parse_response(response, duration):
    words, turns = [], []
    pending = ""
    for result in response.results:
        if not result.alternatives:
            continue
        alternative = result.alternatives[0]
        if alternative.transcript.strip() and not alternative.words:
            raise SpeechRecognitionError
        for word in alternative.words:
            start, end = word.start_time / 1000, word.end_time / 1000
            text = word.word.strip()
            if not text:
                continue
            if not 0 <= start <= end <= duration + 0.32 or word.speaker_tag < 0:
                raise SpeechRecognitionError
            # Riva's frame grid can extend the final token into padded audio.
            # Clip only a bounded (<320 ms) tail; reject larger timestamp drift.
            if start >= duration:
                raise SpeechRecognitionError
            end = min(end, duration)
            # Riva emits zero-duration punctuation/short tokens. Attach their text to
            # a timed neighbour without inventing an interval for the token.
            if start == end:
                if words:
                    sep = "" if text in ",.!?:;" else " "
                    words[-1] = words[-1].model_copy(update={"text": words[-1].text + sep + text})
                else:
                    pending += text + " "
                continue
            words.append(TranscriptionSegment(start=start, end=end, text=pending + text))
            pending = ""
            turns.append(
                SpeakerSegment(start=start, end=end, speaker_id=f"SPEAKER_{word.speaker_tag:02d}")
            )
    if pending:
        raise SpeechRecognitionError
    return TranscriptionResult(segments=words), DiarizationResult(segments=turns)


class NvidiaSpeechAdapter:
    def __init__(self, settings, files):
        self.settings, self.files = settings, files
        self.lock = Lock()
        self.cached = None

    def _recognize(self, audio):
        import grpc
        import riva.client

        if audio.size_bytes > self.settings.nvidia_max_audio_bytes:
            raise SpeechCloudAudioTooLarge
        with self.files.local(audio) as path:
            # Unary API needs bytes; enforce a strict cap before allocation and read.
            with path.open("rb") as stream:
                data = stream.read(self.settings.nvidia_max_audio_bytes + 1)
            if len(data) > self.settings.nvidia_max_audio_bytes:
                raise SpeechCloudAudioTooLarge
        key = self.settings.nvidia_api_key.get_secret_value()
        auth = riva.client.Auth(
            uri="grpc.nvcf.nvidia.com:443",
            use_ssl=True,
            metadata_args=[
                ["function-id", self.settings.nvidia_asr_function_id],
                ["authorization", "Bearer " + key],
            ],
            options=[
                ("grpc.max_send_message_length", self.settings.nvidia_max_audio_bytes + 65536),
                ("grpc.max_receive_message_length", 16 * 1024 * 1024),
            ],
        )
        config = riva.client.RecognitionConfig(
            language_code=self.settings.nvidia_language_code,
            sample_rate_hertz=16000,
            max_alternatives=1,
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True,
        )
        riva.client.add_speaker_diarization_to_config(config, True, 4)
        try:
            response = riva.client.ASRService(auth).stub.Recognize(
                riva.client.proto.riva_asr_pb2.RecognizeRequest(config=config, audio=data),
                timeout=self.settings.nvidia_request_timeout_seconds,
            )
        except grpc.RpcError:
            # Never expose provider details, metadata or credentials through API/logs.
            raise SpeechCloudError from None
        finally:
            auth.channel.close()
        return parse_response(response, audio.duration_seconds)

    def _transcribe(self, audio):
        with self.lock:
            self.cached = None
            pair = self._recognize(audio)
            self.cached = (audio.id, audio.sha256, pair)
            return pair[0]

    async def transcribe(self, audio):
        return await asyncio.to_thread(self._transcribe, audio)

    def _diarize(self, audio):
        with self.lock:
            cached, self.cached = self.cached, None
            if cached is not None and cached[:2] == (audio.id, audio.sha256):
                return cached[2][1]
            return self._recognize(audio)[1]

    async def diarize(self, audio):
        return await asyncio.to_thread(self._diarize, audio)

    def close(self):
        with self.lock:
            self.cached = None
