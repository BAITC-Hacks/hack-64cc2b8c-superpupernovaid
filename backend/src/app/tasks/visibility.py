"""One definition of current tasks for result, export and task-board queries."""

from sqlalchemy import or_, select

from app.audio.models import NormalizedAudio
from app.media.models import MediaAsset
from app.speech.repository import TranscriptRecord
from app.tasks.models import Task


def active_tasks():
    media = (
        select(MediaAsset.id)
        .where(MediaAsset.meeting_id == Task.meeting_id)
        .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        .limit(1)
        .correlate(Task)
        .scalar_subquery()
    )
    transcript = (
        select(TranscriptRecord.id)
        .join(NormalizedAudio, TranscriptRecord.source_audio_id == NormalizedAudio.id)
        .where(NormalizedAudio.source_media_id == media)
        .order_by(TranscriptRecord.created_at.desc(), TranscriptRecord.id.desc())
        .limit(1)
        .correlate(Task)
        .scalar_subquery()
    )
    return or_(Task.origin == "manual", Task.transcript_id == transcript)
