from uuid import NAMESPACE_URL, UUID, uuid5


def segment_uuid(source_id: str) -> UUID:
    """Expose UUIDs without changing stored Speech/Canonicalization source IDs."""
    try:
        return UUID(source_id.removeprefix("seg_"))
    except ValueError:
        return uuid5(NAMESPACE_URL, "qoryt-transcript-segment:" + source_id)
