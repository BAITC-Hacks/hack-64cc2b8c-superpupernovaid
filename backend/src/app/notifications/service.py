"""Database-only reminders: no delivery or SMTP side effects."""

import hashlib
from datetime import UTC, timedelta
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import get_engine
from app.meetings.models import now
from app.notifications.models import Reminder
from app.tasks.models import Task
from app.tasks.visibility import active_tasks


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ReminderService:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def scan(self, at=None):
        at = utc(at or now())
        cutoff = at + timedelta(hours=24)
        created = 0
        # Cancel obsolete records, including old deadline/assignee and stale generated tasks.
        with self.sessions.begin() as s:
            valid = exists(
                select(Task.id).where(
                    Task.id == Reminder.task_id,
                    Task.status != "completed",
                    active_tasks(),
                    Task.due_at == Reminder.due_at,
                    or_(
                        Task.assignee_id == Reminder.assignee_id,
                        and_(Task.assignee_id.is_(None), Reminder.assignee_id.is_(None)),
                    ),
                    or_(
                        and_(Reminder.kind == "overdue", Task.due_at <= at),
                        and_(Reminder.kind == "due_soon", Task.due_at > at, Task.due_at <= cutoff),
                    ),
                )
            )
            s.execute(
                update(Reminder)
                .where(Reminder.status != "cancelled", ~valid)
                .values(status="cancelled")
                .execution_options(synchronize_session=False)
            )
        cursor = None
        while True:
            with self.sessions.begin() as s:
                query = (
                    select(Task)
                    .where(Task.status != "completed", Task.due_at <= cutoff, active_tasks())
                    .order_by(Task.id)
                    .limit(200)
                )
                if cursor:
                    query = query.where(Task.id > cursor)
                tasks = list(s.scalars(query))
                if not tasks:
                    break
                for task in tasks:
                    due = utc(task.due_at)
                    kind = "overdue" if due <= at else "due_soon"
                    key = hashlib.sha256(
                        f"{task.id}|{due.isoformat()}|{task.assignee_id}|{kind}".encode()
                    ).hexdigest()
                    if s.scalar(select(Reminder.id).where(Reminder.dedup_key == key)):
                        continue
                    try:
                        with s.begin_nested():
                            s.add(
                                Reminder(
                                    task_id=task.id,
                                    meeting_id=task.meeting_id,
                                    assignee_id=task.assignee_id,
                                    due_at=due,
                                    kind=kind,
                                    status="pending",
                                    dedup_key=key,
                                    created_at=at,
                                )
                            )
                            s.flush()
                        created += 1
                    except IntegrityError:
                        pass  # Concurrent scan inserted the same reminder.
                cursor = tasks[-1].id
        return {"created": created}

    def list(self, meeting_id=None, status="pending", limit=50, offset=0):
        with self.sessions() as s:
            query = select(Reminder, Task.text).join(Task, Task.id == Reminder.task_id)
            if meeting_id:
                query = query.where(Reminder.meeting_id == meeting_id)
            if status:
                query = query.where(Reminder.status == status)
            rows = s.execute(
                query.order_by(Reminder.created_at.desc(), Reminder.id.desc())
                .offset(offset)
                .limit(limit)
            )
            return [
                {
                    "id": r.id,
                    "meeting_id": r.meeting_id,
                    "task_id": r.task_id,
                    "assignee_id": r.assignee_id,
                    "task": text,
                    "due_at": r.due_at,
                    "kind": r.kind,
                    "status": r.status,
                    "created_at": r.created_at,
                    "read_at": r.read_at,
                }
                for r, text in rows
            ]

    def mark_read(self, ident):
        with self.sessions.begin() as s:
            row = s.get(Reminder, ident)
            if row is None:
                raise HTTPException(404, "Reminder not found")
            if row.status == "pending":
                row.status, row.read_at = "read", now()
            return {"id": row.id, "status": row.status}


@lru_cache
def get_reminders():
    return ReminderService()
