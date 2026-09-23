import logging

from app.speech.adapters.base import LocalModelAdapter
from app.speech.errors import DiarizationError, SpeechModelInitializationError
from app.speech.models import DiarizationResult, SpeakerSegment


def speaker_segments(turns):
    # Relabel consistently across the ENTIRE recording, by first chronological appearance.
    labels, result = {}, []
    for start, end, label in sorted(turns, key=lambda t: (t[0], t[1], str(t[2]))):
        if label not in labels:
            labels[label] = f"SPEAKER_{len(labels):02d}"
        result.append(SpeakerSegment(start=start, end=end, speaker_id=labels[label]))
    return DiarizationResult(segments=result)


class NemoSpeakerDiarizer(LocalModelAdapter):
    async def diarize(self, audio) -> DiarizationResult:
        return await self._run(audio, DiarizationError)

    def _load(self):
        from nemo.collections.asr.models import SortformerEncLabelModel
        from nemo.utils import logging as nemo_logging

        nemo_logging.set_verbosity(logging.ERROR)
        model = SortformerEncLabelModel.restore_from(self.model_path, map_location=self.device)
        if not model.streaming_mode:
            # Streaming Sortformer maintains speaker slots across the full recording.
            # Offline full-attention variants are not the long-form adapter supported here.
            raise SpeechModelInitializationError
        return model.eval()

    def _infer(self, audio):
        with self.files.local(audio, diarization=True) as path:
            output = self._model.diarize(
                audio=[str(path)],
                batch_size=1,
                num_workers=0,
                verbose=False,
                include_tensor_outputs=False,
            )
        if len(output) != 1:
            raise DiarizationError
        turns = []
        for line in output[0]:
            start, end, speaker = line.split()
            turns.append((float(start), float(end), speaker))
        return speaker_segments(turns)


class PyannoteSpeakerDiarizer(LocalModelAdapter):
    async def diarize(self, audio) -> DiarizationResult:
        return await self._run(audio, DiarizationError)

    def _load(self):
        import torch
        from pyannote.audio import Pipeline

        # Local community-1 directory: download/auth is a separate provisioning step.
        pipeline = Pipeline.from_pretrained(self.model_path)
        if pipeline is None:
            raise SpeechModelInitializationError
        return pipeline.to(torch.device(self.device))

    def _infer(self, audio):
        with self.files.local(audio, diarization=True) as path:
            output = self._model(str(path))
        # Preserve simultaneous speakers; do not use exclusive_speaker_diarization.
        annotation = output.speaker_diarization
        return speaker_segments(
            (turn.start, turn.end, speaker)
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        )
