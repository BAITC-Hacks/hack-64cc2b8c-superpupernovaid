from io import BytesIO
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.application.ports import FileStorageError
from app.infrastructure.storage import S3FileStorage


@pytest.mark.parametrize("key", ["../escape", "/absolute", "a/../../escape", r"a\escape", "a//b"])
def test_reject_unsafe_keys(storage, key):
    with pytest.raises(FileStorageError):
        storage.save(key, [b"content"], "audio/wav")


def test_reject_symlink_escape(storage, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    storage.root.mkdir()
    (storage.root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileStorageError):
        storage.save("link/source", [b"content"], "audio/wav")
    assert not list(outside.iterdir())


def test_no_overwrite(storage):
    storage.save("meeting/asset/source", [b"original"], "audio/wav")
    with pytest.raises(FileStorageError):
        storage.save("meeting/asset/source", [b"replacement"], "audio/wav")
    with storage.open("meeting/asset/source") as stream:
        assert stream.read() == b"original"


def test_delete_idempotent(storage):
    storage.save("meeting/asset/source", [b"content"], "audio/wav")
    storage.delete("meeting/asset/source")
    storage.delete("meeting/asset/source")


def test_write_failure_is_controlled(storage):
    storage.root.write_bytes(b"not a directory")
    with pytest.raises(FileStorageError):
        storage.save("meeting/asset/source", [b"content"], "audio/wav")


def test_missing_file_is_controlled(storage):
    with pytest.raises(FileStorageError), storage.open("meeting/missing/source"):
        pass


def test_s3_implements_streaming_contract_without_network():
    adapter = object.__new__(S3FileStorage)
    adapter.bucket = "test"
    adapter.client = Mock()

    def upload(stream, bucket, key, **kwargs):
        assert bucket == "test" and key == "meeting/asset/source"
        assert stream.read(2) == b"ab"
        assert stream.read(2) == b"cd"

    adapter.client.upload_fileobj.side_effect = upload
    assert adapter.save("meeting/asset/source", iter([b"ab", b"cd"]), "audio/wav") == 4
    body = BytesIO(b"abcd")
    adapter.client.get_object.return_value = {"Body": body}
    with adapter.open("meeting/asset/source") as stream:
        assert stream.read(2) == b"ab"
    assert body.closed
    adapter.delete("meeting/asset/source")
    adapter.client.delete_object.assert_called_once()
    adapter.client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "private details"}}, "GetObject"
    )
    with pytest.raises(FileStorageError), adapter.open("missing"):
        pass
