from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.audio.models import NormalizedAudio
from app.infrastructure.database import get_engine
from app.media.models import MediaAsset
from app.meetings.models import Meeting, ProcessingStep, now


class ProcessingTracker:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def update(self, media_id, stage, status):
        with self.sessions.begin() as s:
            media = s.get(MediaAsset, media_id)
            if media is None:
                return
            row = s.get(ProcessingStep, (media_id, stage))
            if row is None:
                row = ProcessingStep(media_id=media_id, stage=stage)
                s.add(row)
            row.status = status
            row.updated_at = now()
            row.message = {
                "running": "Processing",
                "completed": "Completed",
                "failed": "Processing failed; retry the stage",
            }[status]
            meeting = s.get(Meeting, media.meeting_id)
            latest = s.scalar(
                select(MediaAsset.id)
                .where(MediaAsset.meeting_id == media.meeting_id)
                .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
                .limit(1)
            )
            # A full pipeline owns the meeting state until exports finish. Individual
            # service trackers may report substeps but cannot declare the meeting ready.
            from app.processing.models import ProcessingRun

            run = s.get(ProcessingRun, media.meeting_id)
            if run and run.media_id == media_id and run.status in {"queued", "running"}:
                if run.status == "running":
                    run.steps = {**run.steps, stage: status}
                    run.updated_at = now()
                    if status == "running":
                        run.stage = stage
                        if meeting and latest == media_id:
                            meeting.processing_status = stage
                return
            if meeting and latest == media_id:
                meeting.processing_status = "failed" if status == "failed" else stage
                if status == "completed":
                    meeting.processing_status = {
                        "uploaded": "uploaded",
                        "preprocessing": "transcribing",
                        "transcribing": "diarizing",
                        "diarizing": "analyzing",
                        "analyzing": "ready",
                    }[stage]
                if status == "completed":
                    from app.intelligence.models import MeetingAnalysis
                    from app.meetings.repository import latest_transcript

                    transcript = latest_transcript(s, meeting.id)
                    if transcript:
                        meeting.processing_status = (
                            "ready" if s.get(MeetingAnalysis, transcript.id) else "analyzing"
                        )
                meeting.updated_at = now()

    def speech(self, audio, stage, status):
        with self.sessions() as s:
            saved = s.get(NormalizedAudio, audio.id)
            media_id = saved.source_media_id if saved else None
        if media_id:
            self.update(media_id, stage, status)
