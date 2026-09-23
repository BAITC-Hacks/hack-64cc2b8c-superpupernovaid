from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from app.application.ports import FileStorageError, FileStorageNotFoundError


class LocalMediaStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if (
            not key
            or relative.is_absolute()
            or "\\" in key
            or any(part in {"", ".", ".."} for part in key.split("/"))
        ):
            raise FileStorageError("Invalid storage reference")
        try:
            path = (self.root / relative).resolve()
        except (OSError, RuntimeError) as exc:
            raise FileStorageError("Invalid storage reference") from exc
        if not path.is_relative_to(self.root):
            raise FileStorageError("Invalid storage reference")
        return path

    def save(self, key: str, chunks: Iterable[bytes], content_type: str) -> int:
        path = self._path(key)
        created = False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                created = True
                total = 0
                for chunk in chunks:
                    output.write(chunk)
                    total += len(chunk)
            return total
        except BaseException as exc:
            # Never delete an existing object when exclusive creation failed.
            if created:
                try:
                    path.unlink(missing_ok=True)
                    path.parent.rmdir()
                except OSError:
                    pass
            if isinstance(exc, OSError):
                raise FileStorageError("Storage write failed") from exc
            raise

    @contextmanager
    def open(self, key: str) -> Iterator[BinaryIO]:
        try:
            stream = self._path(key).open("rb")
        except FileNotFoundError as exc:
            raise FileStorageNotFoundError("Storage object not found") from exc
        except OSError as exc:
            raise FileStorageError("Storage read failed") from exc
        try:
            yield stream
        finally:
            stream.close()

    def delete(self, key: str) -> None:
        try:
            path = self._path(key)
            path.unlink(missing_ok=True)
            # Empty per-asset directories are disposable; meeting directories can remain.
            try:
                path.parent.rmdir()
            except OSError:
                pass
        except OSError as exc:
            raise FileStorageError("Storage delete failed") from exc
