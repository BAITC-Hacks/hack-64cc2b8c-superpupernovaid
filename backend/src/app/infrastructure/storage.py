from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from tempfile import TemporaryFile
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.application.ports import FileStorageError
from app.config import Settings


class S3FileStorage:
    """Existing adapter, now implementing the same streaming FileStorage boundary."""

    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )

    def save(self, key: str, chunks: Iterable[bytes], content_type: str) -> int:
        try:
            # Validate/consume the bounded iterator before publishing an object. Disk, not RAM.
            # boto3 handles multipart uploads and aborts incomplete uploads on failure.
            with TemporaryFile() as stream:
                size = 0
                for chunk in chunks:
                    stream.write(chunk)
                    size += len(chunk)
                stream.seek(0)
                self.client.upload_fileobj(
                    stream, self.bucket, key, ExtraArgs={"ContentType": content_type}
                )
            return size
        except (OSError, BotoCoreError, ClientError) as exc:
            raise FileStorageError("Storage write failed") from exc

    @contextmanager
    def open(self, key: str) -> Iterator[BinaryIO]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                yield body
            finally:
                body.close()
        except (OSError, BotoCoreError, ClientError) as exc:
            raise FileStorageError("Storage read failed") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise FileStorageError("Storage delete failed") from exc

    def put(self, key: str, content: bytes, content_type: str) -> None:
        # Retained for compatibility with the initial scaffold's small-object API.
        self.save(key, [content], content_type)

    def download_url(self, key: str, expires: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )
