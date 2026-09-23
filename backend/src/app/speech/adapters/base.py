import asyncio
import gc
import logging
import time
from threading import Lock

from app.speech.errors import SpeechModelInitializationError, SpeechProcessingError

logger = logging.getLogger(__name__)


class LocalModelAdapter:
    """One lazy model per cached adapter, lock protects initialization AND native inference."""

    def __init__(self, model_path, device, files):
        self.model_path, self.device, self.files = str(model_path), device, files
        self._model = None
        self._lock = Lock()
        self._initialization_failed = False

    async def _run(self, audio, error_type):
        return await asyncio.to_thread(self._locked_run, audio, error_type)

    def _locked_run(self, audio, error_type):
        with self._lock:
            if self._initialization_failed:
                raise SpeechModelInitializationError
            if self._model is None:
                start = time.monotonic()
                try:
                    self._model = self._load()
                except Exception as exc:
                    self._initialization_failed = True
                    raise SpeechModelInitializationError from exc
                logger.info(
                    "speech_model_loaded adapter=%s device=%s elapsed=%.3f",
                    type(self).__name__,
                    self.device,
                    time.monotonic() - start,
                )
            try:
                return self._infer(audio)
            except SpeechProcessingError:
                raise
            except Exception as exc:
                raise error_type from exc

    def close(self):
        with self._lock:
            self._model = None
            gc.collect()
            # Do not import Torch merely to shut down a CPU/Whisper-only application.
            import sys

            torch = sys.modules.get("torch")
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
