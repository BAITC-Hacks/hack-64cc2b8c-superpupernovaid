import math

from app.protocols.models import MeetingProtocol, ProtocolSegment, TextMode


def timestamp(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Timestamp must be finite and non-negative")
    total = math.floor(seconds)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def segment_text(segment: ProtocolSegment, mode: TextMode) -> str:
    if mode == "canonical" and segment.canonical_text is not None:
        return segment.canonical_text
    return segment.original_text


def segment_heading(segment: ProtocolSegment) -> str:
    return f"[{timestamp(segment.start)}] {segment.participant_name or segment.speaker_id}"


def action_table(protocol: MeetingProtocol):
    status = any(item.status is not None for item in protocol.action_items)
    header = ["№", "Поручение", "Ответственный", "Срок"] + (["Статус"] if status else [])
    rows = []
    for number, item in enumerate(protocol.action_items, 1):
        row = [
            str(number),
            item.text,
            item.assignee or "Не определён",
            item.deadline or "Не указан",
        ]
        if status:
            row.append(item.status if item.status is not None else "")
        rows.append(row)
    return header, rows
