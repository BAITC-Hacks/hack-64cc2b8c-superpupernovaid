from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.bootstrap import get_media_repository
from app.canonicalization.dependencies import (
    get_canonicalization_service,
    get_canonicalization_speech_repository,
)
from app.canonicalization.errors import (
    CanonicalizationProviderError,
    CanonicalizationValidationError,
)
from app.config import get_settings
from app.entrypoints.api import app
from app.speech.dependencies import get_speech_audio_repository


def test_route_preserves_contract_and_controls_stage_errors(service, transcript, settings):
    meeting_id, media_id = uuid4(), uuid4()
    media = SimpleNamespace(
        get=lambda meeting, media: (
            SimpleNamespace(id=media_id) if meeting == meeting_id and media == media_id else None
        )
    )
    audio = SimpleNamespace(find=lambda *a: SimpleNamespace(id=transcript.source_audio_id))
    speech = SimpleNamespace(find=lambda *a: transcript)
    overrides = {
        get_media_repository: lambda: media,
        get_speech_audio_repository: lambda: audio,
        get_canonicalization_speech_repository: lambda: speech,
        get_canonicalization_service: lambda: service,
        get_settings: lambda: settings,
    }
    app.dependency_overrides.update(overrides)
    url = f"/api/v1/meetings/{meeting_id}/media/{media_id}/canonicalize"
    try:
        with TestClient(app) as client:
            response = client.post(url)
            assert response.status_code == 200
            assert response.json()["segments"][0]["original_text"] == transcript.segments[0].text
            assert "unit-fake-key" not in response.text
            assert client.post(url.replace(str(meeting_id), str(uuid4()))).status_code == 404
            for error, status in [
                (CanonicalizationProviderError, 503),
                (CanonicalizationValidationError, 502),
            ]:

                async def fail(transcript):
                    raise error from RuntimeError("secret text")

                service.canonicalize = fail
                response = client.post(url)
                assert response.status_code == status and "secret text" not in response.text
            app.dependency_overrides[get_canonicalization_service] = lambda: None
            assert client.post(url).status_code == 503
            speech.find = lambda *a: None
            assert client.post(url).json()["detail"]["code"] == "speech_processing_required"
            audio.find = lambda *a: None
            assert client.post(url).json()["detail"]["code"] == "audio_preprocessing_required"
    finally:
        for key in overrides:
            app.dependency_overrides.pop(key, None)
