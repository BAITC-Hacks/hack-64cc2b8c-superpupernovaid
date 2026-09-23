import asyncio
from uuid import uuid4

import pytest

from app.config import get_settings
from app.entrypoints.api import app
from app.media.errors import (
    InvalidMediaError,
    MediaPersistenceError,
    MediaProbeError,
    MediaStorageError,
    MediaTooLargeError,
    UnsupportedMediaError,
)
from app.media.router import MULTIPART_OVERHEAD


def test_upload_and_get(client, meeting_id):
    path = f"/api/v1/meetings/{meeting_id}/media"
    response = client.post(path, files={"file": ("fake.mp4", b"audio", "video/mp4")})
    assert response.status_code == 201
    asset = response.json()
    # Mock probe says audio despite spoofed extension/MIME.
    assert asset["media_type"] == "audio"
    assert asset["mime_type"] == "audio/wav"
    assert client.get(f"{path}/{asset['id']}").json()["storage_key"] == asset["storage_key"]
    assert client.get(f"/api/v1/meetings/{uuid4()}/media/{asset['id']}").status_code == 404
    assert client.get(f"{path}/{uuid4()}").status_code == 404


@pytest.mark.parametrize(
    "error",
    [
        InvalidMediaError,
        UnsupportedMediaError,
        MediaTooLargeError,
        MediaProbeError,
        MediaStorageError,
        MediaPersistenceError,
    ],
)
def test_domain_error_mapping(client, meeting_id, service, monkeypatch, error):
    def fail(*args):
        raise error("secret internal filesystem details")

    monkeypatch.setattr(service, "ingest", fail)
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/media", files={"file": ("a.wav", b"input")}
    )
    assert response.status_code == error.http_status
    assert response.json()["detail"]["code"] == error.code
    assert "secret" not in response.text


def test_multipart_and_uuid_validation(client, meeting_id):
    url = f"/api/v1/meetings/{meeting_id}/media"
    assert client.post(url).status_code == 422
    assert (
        client.post(
            "/api/v1/meetings/not-a-uuid/media", files={"file": ("a.wav", b"input")}
        ).status_code
        == 422
    )
    assert (
        client.post(url, files=[("file", ("a.wav", b"a")), ("file", ("b.wav", b"b"))]).status_code
        == 400
    )
    assert (
        client.post(
            url, files={"file": ("a.wav", b"input")}, data={"asr_model": "not-accepted"}
        ).status_code
        == 400
    )


def test_file_limit_without_full_body_limit(client, service, meeting_id):
    service.max_bytes = 3
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/media", files={"file": ("a.wav", b"1234")}
    )
    assert response.status_code == 413


def test_body_limit_checked_before_reading(client, meeting_id, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_max_file_size_bytes", 10)
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/media",
        content=b"",
        headers={"Content-Length": str(MULTIPART_OVERHEAD + 11)},
    )
    assert response.status_code == 413


def test_chunked_body_limit_closes_spooled_file(client, meeting_id, monkeypatch):
    import starlette.formparsers as parser

    monkeypatch.setattr(get_settings(), "media_max_file_size_bytes", 10)
    created = []
    real = parser.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        file = real(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(parser, "SpooledTemporaryFile", tracked)
    chunks = iter(
        [
            b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.wav"\r\n\r\n',
            b"x" * (MULTIPART_OVERHEAD + 11),
        ]
    )
    messages = []

    async def receive():
        return {"type": "http.request", "body": next(chunks), "more_body": True}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/v1/meetings/{meeting_id}/media",
        "query_string": b"",
        "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    assert messages[0]["status"] == 413
    assert created and all(file.closed for file in created)


def test_swagger_multipart_contract(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/meetings/{meeting_id}/media"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    assert "201" in operation["responses"]


def test_multipart_disk_failure_is_controlled(client, meeting_id, monkeypatch):
    import starlette.formparsers as parser

    def unavailable(*args, **kwargs):
        raise OSError("private temporary path")

    monkeypatch.setattr(parser, "SpooledTemporaryFile", unavailable)
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/media", files={"file": ("a.wav", b"input")}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "media_storage_unavailable"
    assert "private" not in response.text


def test_upload_requires_existing_meeting_and_recording_consent(client, meeting_id, repository):
    from sqlalchemy import select

    from app.meetings.models import RecordingConsent

    missing = client.post(f"/api/v1/meetings/{uuid4()}/media", files={"file": ("x.wav", b"a")})
    assert missing.status_code == 404
    with repository.sessions.begin() as session:
        consent = session.scalar(
            select(RecordingConsent).where(RecordingConsent.meeting_id == meeting_id)
        )
        consent.confirmed = False
    rejected = client.post(f"/api/v1/meetings/{meeting_id}/media", files={"file": ("x.wav", b"a")})
    assert rejected.status_code == 409
