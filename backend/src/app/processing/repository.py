from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import get_engine
from app.meetings.models import Meeting, now
from app.meetings.repository import latest_media
from app.processing.errors import ProcessingConflict, ProcessingNotFound
from app.processing.models import STAGES, ProcessingRun, RunView


class ProcessingRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(
            bind=engine if engine is not None else get_engine(), expire_on_commit=False
        )

    def _input(self, session, meeting_id, media_id):
        meeting = session.get(Meeting, meeting_id)
        media = latest_media(session, meeting_id)
        if meeting is None or media is None:
            raise ProcessingNotFound
        if media.id != media_id:
            raise ProcessingConflict
        return meeting, media

    def language(self, meeting_id, media_id):
        with self.sessions() as s:
            meeting, _ = self._input(s, meeting_id, media_id)
            return meeting.language_hint

    def submit(self, meeting_id, payload):
        try:
            with self.sessions.begin() as s:
                meeting, _ = self._input(s, meeting_id, payload.media_id)
                row = s.get(ProcessingRun, meeting_id)
                formats = sorted(set(payload.export_formats))
                if row and row.status in {"queued", "running"}:
                    if row.media_id != payload.media_id or row.export_formats != formats:
                        raise ProcessingConflict
                    return RunView.model_validate(row), False
                if (
                    row
                    and row.status == "completed"
                    and not payload.refresh
                    and row.media_id == payload.media_id
                    and row.export_formats == formats
                ):
                    return RunView.model_validate(row), False
                values = dict(
                    id=uuid4(),
                    media_id=payload.media_id,
                    status="queued",
                    stage=None,
                    steps={stage: "pending" for stage in STAGES},
                    export_formats=formats,
                    exports=[],
                    error_code=None,
                    error_message=None,
                    created_at=now(),
                    updated_at=now(),
                )
                if row:
                    changed = s.execute(
                        update(ProcessingRun)
                        .where(
                            ProcessingRun.meeting_id == meeting_id,
                            ProcessingRun.id == row.id,
                            ProcessingRun.status == row.status,
                        )
                        .values(**values)
                    ).rowcount
                    if not changed:
                        raise ProcessingConflict
                    s.expire(row)
                else:
                    row = ProcessingRun(meeting_id=meeting_id, **values)
                    s.add(row)
                meeting.processing_status = "queued"
                s.flush()
                return RunView.model_validate(row), True
        except IntegrityError:
            # Another request won the unique meeting key. It owns publication.
            row = self.get(meeting_id)
            if row.media_id != payload.media_id or row.export_formats != sorted(
                set(payload.export_formats)
            ):
                raise ProcessingConflict from None
            return row, False

    def get(self, meeting_id):
        with self.sessions() as s:
            row = s.get(ProcessingRun, meeting_id)
            if row is None:
                raise ProcessingNotFound
            return RunView.model_validate(row)

    def claim(self, run_id):
        with self.sessions.begin() as s:
            changed = s.execute(
                update(ProcessingRun)
                .where(ProcessingRun.id == run_id, ProcessingRun.status == "queued")
                .values(status="running", updated_at=now())
            ).rowcount
            if not changed:
                return None
            row = s.scalar(select(ProcessingRun).where(ProcessingRun.id == run_id))
            return RunView.model_validate(row)

    def transition(self, run_id, stage, state):
        with self.sessions.begin() as s:
            row = s.scalar(
                select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update()
            )
            if row is None or row.status != "running":
                raise ProcessingConflict
            meeting, _ = self._input(s, row.meeting_id, row.media_id)
            row.stage = stage
            row.steps = {**row.steps, stage: state}
            row.updated_at = now()
            meeting.processing_status = stage
            meeting.updated_at = now()

    def finish(self, run_id, exports):
        with self.sessions.begin() as s:
            row = s.scalar(
                select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update()
            )
            if row is None or row.status != "running":
                raise ProcessingConflict
            meeting, _ = self._input(s, row.meeting_id, row.media_id)
            row.status, row.exports, row.updated_at = "completed", exports, now()
            meeting.processing_status, meeting.updated_at = "ready", now()

    def fail(self, run_id, code, message, *, only_queued=False):
        with self.sessions.begin() as s:
            row = s.scalar(
                select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update()
            )
            if row is None or row.status not in (
                {"queued"} if only_queued else {"queued", "running"}
            ):
                return
            row.status, row.error_code, row.error_message = "failed", code, message
            if row.stage:
                row.steps = {**row.steps, row.stage: "failed"}
            row.updated_at = now()
            media = latest_media(s, row.meeting_id)
            if media and media.id == row.media_id:
                meeting = s.get(Meeting, row.meeting_id)
                meeting.processing_status, meeting.updated_at = "failed", now()
