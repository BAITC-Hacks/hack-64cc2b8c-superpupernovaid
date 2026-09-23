from threading import BoundedSemaphore
from uuid import uuid4

import pytest

from app.audio.errors import AudioProcessingBusyError, AudioProcessingTimeoutError


def test_endpoint_and_idempotency(client, media):
    url = f"/api/v1/meetings/{media.meeting_id}/media/{media.id}/preprocess"
    response = client.post(url)
    assert response.status_code == 200, response.text
    assert response.json()["source_media_id"] == str(media.id)
    assert response.json()["sample_rate"] == 16000
    assert client.post(url).json()["id"] == response.json()["id"]
    assert client.post(f"/api/v1/meetings/{uuid4()}/media/{media.id}/preprocess").status_code == 404


@pytest.mark.parametrize("error", [AudioProcessingTimeoutError, AudioProcessingBusyError])
def test_error_mapping(client, media, preprocessor, monkeypatch, error):
    async def fail(*args):
        raise error("private stderr")

    monkeypatch.setattr(preprocessor, "process", fail)
    response = client.post(f"/api/v1/meetings/{media.meeting_id}/media/{media.id}/preprocess")
    assert response.status_code == error.http_status
    assert response.json()["detail"]["code"] == error.code
    assert "private" not in response.text
    if error.http_status == 429:
        assert response.headers["retry-after"] == "5"


def test_upload_rejected_before_read_when_capacity_full(client, media, monkeypatch):
    import app.media.router as router

    capacity = BoundedSemaphore(1)
    capacity.acquire()
    monkeypatch.setattr(router, "get_upload_capacity", lambda: capacity)

    def unread_body():
        raise AssertionError("Overload response should not read/spool body")
        yield b""

    response = client.post(
        f"/api/v1/meetings/{media.meeting_id}/media",
        content=unread_body(),
        headers={"Content-Type": "multipart/form-data; boundary=test"},
    )
    assert response.status_code == 429 and response.headers["retry-after"] == "5"
