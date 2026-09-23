import logging
import math

from app.speech.adapters.base import LocalModelAdapter
from app.speech.errors import SpeechRecognitionError
from app.speech.models import TranscriptionResult, TranscriptionSegment


def append_words(result, words, window):
    """Keep words owned by this core window; overlap is context, not duplicate output."""
    for start, end, text in words:
        start, end = float(start) + window.offset, float(end) + window.offset
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise SpeechRecognitionError
        if window.keep_start <= (start + end) / 2 < window.keep_end:
            word = TranscriptionSegment(start=start, end=end, text=text)
            # The same boundary word may have slightly different timestamps in two windows.
            if result and result[-1].text == word.text and word.start < result[-1].end:
                continue
            result.append(word)


class NemoSpeechRecognizer(LocalModelAdapter):
    async def transcribe(self, audio) -> TranscriptionResult:
        return await self._run(audio, SpeechRecognitionError)

    def _load(self):
        from nemo.collections.asr.models import ASRModel
        from nemo.utils import logging as nemo_logging

        nemo_logging.set_verbosity(logging.ERROR)
        # Fully local restore; no NVIDIA cloud API/key dependency.
        return ASRModel.restore_from(self.model_path, map_location=self.device).eval()

    def _infer(self, audio):
        result = []
        with self.files.local(audio) as path:
            for window in self.files.windows(path):
                hypotheses = self._model.transcribe(
                    [str(window.path)],
                    batch_size=1,
                    timestamps=True,
                    return_hypotheses=True,
                    num_workers=0,
                    verbose=False,
                )
                if len(hypotheses) != 1:
                    raise SpeechRecognitionError
                hypothesis = hypotheses[0]
                timestamps = getattr(hypothesis, "timestamp", None)
                words = timestamps.get("word") if isinstance(timestamps, dict) else None
                if words is None:
                    # Never fabricate timings for text-only NeMo checkpoints.
                    raise SpeechRecognitionError
                if getattr(hypothesis, "text", "").strip() and not words:
                    raise SpeechRecognitionError
                append_words(result, ((w["start"], w["end"], w["word"]) for w in words), window)
        return TranscriptionResult(segments=result)


class WhisperSpeechRecognizer(LocalModelAdapter):
    def __init__(self, model_path, device, files, compute_type="default"):
        super().__init__(model_path, device, files)
        self.compute_type = compute_type

    async def transcribe(self, audio) -> TranscriptionResult:
        return await self._run(audio, SpeechRecognitionError)

    def _load(self):
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.model_path,
            device=self.device,
            compute_type=self.compute_type,
            local_files_only=True,
            num_workers=1,
        )

    def _infer(self, audio):
        result = []
        with self.files.local(audio) as path:
            for window in self.files.windows(path):
                segments, _ = self._model.transcribe(
                    str(window.path),
                    word_timestamps=True,
                    vad_filter=False,
                    condition_on_previous_text=False,
                )
                for segment in segments:
                    if segment.text.strip() and not segment.words:
                        raise SpeechRecognitionError
                    append_words(
                        result, ((w.start, w.end, w.word) for w in (segment.words or [])), window
                    )
        return TranscriptionResult(segments=result)
