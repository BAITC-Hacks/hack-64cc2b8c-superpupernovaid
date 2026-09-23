from collections.abc import Iterator
from typing import BinaryIO

from app.media.errors import InvalidMediaError, MediaStorageError, MediaTooLargeError

CHUNK_SIZE = 1024 * 1024
# Names are ffprobe demuxer families, not client filename suffixes.
SUPPORTED_FORMATS = frozenset({"wav", "mp3", "flac", "ogg", "mov", "matroska"})


def display_filename(filename: str) -> str:
    # Retain a display name only; never use it in a storage path or subprocess argument.
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable()).strip()
    if not name or name in {".", ".."}:
        raise InvalidMediaError
    return name[:255]


def limited_chunks(source: BinaryIO, maximum: int) -> Iterator[bytes]:
    total = 0
    while True:
        try:
            chunk = source.read(CHUNK_SIZE)
        except (OSError, ValueError) as exc:
            raise MediaStorageError from exc
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise MediaTooLargeError
        yield chunk
    if total == 0:
        raise InvalidMediaError
