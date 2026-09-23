from datetime import UTC
from functools import lru_cache
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import get_engine
from app.meetings.identifiers import segment_uuid
from app.meetings.models import ChangeAudit, Participant, now
from app.meetings.repository import cursor_encode, latest_transcript, page_after, require_meeting
from app.tasks.models import Task
from app.tasks.schemas import TaskView


def task_view(session, row):
    assignee = session.get(Participant, row.assignee_id) if row.assignee_id else None
    due = row.due_at
    if due and due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    status = (
        "completed"
        if row.status == "completed"
        else ("overdue" if due and due < now() else "in_progress")
    )
    current = latest_transcript(session, row.meeting_id)
    references = row.source_segment_ids if current and row.transcript_id == current.id else []
    return TaskView(
        id=row.id,
        meeting_id=row.meeting_id,
        text=row.text,
        assignee={"id": assignee.id, "display_name": assignee.display_name} if assignee else None,
        due_at=due,
        status=status,
        priority=row.priority,
        source_segment_ids=references,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def check_assignee(session, meeting_id, assignee_id):
    if assignee_id:
        row = session.get(Participant, assignee_id)
        if row is None or row.meeting_id != meeting_id:
            raise HTTPException(422, "Assignee must belong to this meeting")


class TaskRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def list(
        self,
        *,
        meeting_id=None,
        status=None,
        assignee_id=None,
        due_before=None,
        q=None,
        cursor=None,
        limit=50,
    ):
        with self.sessions() as s:
            if meeting_id:
                require_meeting(s, meeting_id)
            from app.tasks.visibility import active_tasks

            query = select(Task).where(active_tasks())
            if meeting_id:
                query = query.where(Task.meeting_id == meeting_id)
            if assignee_id:
                query = query.where(Task.assignee_id == assignee_id)
            if due_before:
                query = query.where(Task.due_at < due_before)
            if q:
                query = query.where(Task.text.icontains(q, autoescape=True))
            if status == "completed":
                query = query.where(Task.status == "completed")
            elif status == "overdue":
                query = query.where(Task.status != "completed", Task.due_at < now())
            elif status == "in_progress":
                query = query.where(
                    Task.status != "completed", or_(Task.due_at.is_(None), Task.due_at >= now())
                )
            rows = list(s.scalars(page_after(query, Task.id, cursor).limit(limit + 1)))
            return {
                "items": [task_view(s, r) for r in rows[:limit]],
                "next_cursor": cursor_encode(str(rows[limit - 1].id))
                if len(rows) > limit
                else None,
            }

    def create(self, meeting_id, payload):
        with self.sessions.begin() as s:
            require_meeting(s, meeting_id)
            check_assignee(s, meeting_id, payload.assignee_id)
            record = latest_transcript(s, meeting_id)
            valid = (
                {str(segment_uuid(x["id"])) for x in record.payload["segments"]}
                if record
                else set()
            )
            if not {str(x) for x in payload.source_segment_ids} <= valid:
                raise HTTPException(
                    422, "Source segments must belong to the current meeting transcript"
                )
            row = Task(
                id=uuid4(),
                meeting_id=meeting_id,
                transcript_id=record.id if record else None,
                text=payload.text,
                assignee_id=payload.assignee_id,
                due_at=payload.due_at,
                priority=payload.priority,
                source_segment_ids=[str(x) for x in payload.source_segment_ids],
            )
            s.add(row)
            s.flush()
            s.add(
                ChangeAudit(
                    meeting_id=meeting_id,
                    entity_id=row.id,
                    action="task.create",
                    changes=payload.model_dump(mode="json"),
                )
            )
            return task_view(s, row)

    def patch(self, ident, payload):
        with self.sessions.begin() as s:
            row = s.get(Task, ident)
            if row is None:
                raise HTTPException(404, "Task not found")
            changes = payload.model_dump(exclude_unset=True)
            if "assignee_id" in changes:
                check_assignee(s, row.meeting_id, changes["assignee_id"])
            # Overdue is derived from the deadline; it is not an independently writable state.
            if changes.get("status") == "overdue":
                due = changes.get("due_at", row.due_at)
                if due and due.tzinfo is None:
                    due = due.replace(tzinfo=UTC)
                if not due or due >= now():
                    raise HTTPException(422, "Overdue requires a past due_at")
                changes["status"] = "in_progress"
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = now()
            s.add(
                ChangeAudit(
                    meeting_id=row.meeting_id,
                    entity_id=row.id,
                    action="task.patch",
                    changes=payload.model_dump(mode="json", exclude_unset=True),
                )
            )
            s.flush()
            return task_view(s, row)


@lru_cache
def get_tasks():
    return TaskRepository()
