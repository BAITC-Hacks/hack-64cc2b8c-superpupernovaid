from uuid import uuid4

from fastapi.testclient import TestClient

from app.audio.repository import AudioRepository
from app.bootstrap import get_media_repository
from app.config import Settings, get_settings
from app.entrypoints.api import app
from app.media.repository import MediaRepository
from app.speech.dependencies import get_speech_audio_repository, get_speech_service
from app.speech.errors import SpeechBusyError, SpeechModelInitializationError


def test_http_pipeline_scope_errors_and_secret(engine, audio, service):
    media = MediaRepository(engine)
    meeting_id = audio.storage_key.split("/")[0]
    url = f"/api/v1/meetings/{meeting_id}/media/{audio.source_media_id}/speech"
    overrides = {
        get_media_repository: lambda: media,
        get_speech_audio_repository: lambda: AudioRepository(engine),
        get_speech_service: lambda: service,
        get_settings: lambda: Settings(_env_file=None, nvidia_api_key="http-test-secret"),
    }
    app.dependency_overrides.update(overrides)
    try:
        with TestClient(app) as client:
            result = client.post(url)
            assert result.status_code == 200
            assert result.json()["source_audio_id"] == str(audio.id)
            assert set(result.json()) == {"source_audio_id", "segments"}
            assert "http-test-secret" not in result.text
            assert client.post(url).json() == result.json()
            assert client.post(url.replace(meeting_id, str(uuid4()))).status_code == 404
            for error, status in [(SpeechBusyError, 429), (SpeechModelInitializationError, 503)]:

                async def fail(audio):
                    raise error from RuntimeError("http-test-secret")

                service.process = fail
                response = client.post(url)
                assert response.status_code == status and "http-test-secret" not in response.text
                if status == 429:
                    assert response.headers["Retry-After"] == "5"
            app.dependency_overrides[get_speech_service] = lambda: None
            assert client.post(url).json()["detail"]["code"] == "speech_disabled"
            AudioRepository(engine).remove(audio.id)
            assert client.post(url).status_code == 409
    finally:
        for key in overrides:
            app.dependency_overrides.pop(key, None)
