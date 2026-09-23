import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.models import MeetingAnalysis
from app.notifications.models import Reminder
from app.notifications.service import ReminderService
from app.protocols.presentation import action_table
from app.protocols.versions import ProtocolVersion, load_version
from app.tasks.models import Task

from .test_api_loader import database as shared_database
from .test_api_loader import publish
from .test_service import service as shared_service


@pytest.fixture
def database(tmp_path, protocol):
    yield from shared_database.__wrapped__(tmp_path, protocol)


@pytest.fixture
def service(tmp_path):
    return shared_service.__wrapped__(tmp_path)


def test_versions_freeze_content_and_deduplicate(protocol, service):
    first = asyncio.run(service.export(protocol, "docx"))
    again = asyncio.run(service.export(protocol, "docx"))
    assert first.version_id == again.version_id
    changed = protocol.model_copy(update={"title": "Изменено", "summary": "Новое резюме"})
    second = asyncio.run(service.export(changed, "docx"))
    assert first.version_id != second.version_id
    old = load_version(service.repository.sessions, protocol.meeting_id, first.version_id)
    assert old.title == protocol.title and old.summary == protocol.summary
    with service.repository.sessions() as session:
        assert len(list(session.scalars(select(ProtocolVersion)))) == 2
    with pytest.raises(HTTPException) as exc:
        load_version(service.repository.sessions, uuid4(), first.version_id)
    assert exc.value.status_code == 404


def test_original_deadline_survives_without_inventing_date(database, protocol):
    from app.protocols.loader import ProtocolLoader

    engine, _ = database
    publish(engine, protocol)
    task_id = uuid4()
    from app.meetings.identifiers import segment_uuid

    with Session(engine) as s, s.begin():
        analysis = s.get(MeetingAnalysis, protocol.source_transcript_id)
        analysis.details = {"action_items": [{"id": str(task_id), "deadline_text": "до пятницы"}]}
        s.add(
            Task(
                id=task_id,
                meeting_id=protocol.meeting_id,
                transcript_id=protocol.source_transcript_id,
                origin="generated",
                text="Проверить",
                source_segment_ids=[str(segment_uuid("seg_abc"))],
            )
        )
    item = ProtocolLoader(engine).load(protocol.meeting_id).action_items[0]
    assert item.deadline is None and item.deadline_text == "до пятницы"
    with Session(engine) as s, s.begin():
        s.get(Task, task_id).due_at = datetime(2026, 10, 2, 10, tzinfo=UTC)
    loaded = ProtocolLoader(engine).load(protocol.meeting_id)
    rendered = action_table(loaded)[1][0][3]
    assert "2026-10-02" in rendered and "Исходно: до пятницы" in rendered


def test_reminders_are_idempotent_and_cancel_obsolete_deadlines(database, protocol):
    engine, _ = database
    at = datetime(2026, 10, 1, 10, tzinfo=UTC)
    task_id, no_due = uuid4(), uuid4()
    with Session(engine) as s, s.begin():
        s.add(
            Task(
                id=task_id,
                meeting_id=protocol.meeting_id,
                text="Сдать отчёт",
                due_at=at + timedelta(hours=1),
            )
        )
        s.add(Task(id=no_due, meeting_id=protocol.meeting_id, text="Без срока"))
    reminders = ReminderService(engine)
    assert reminders.scan(at) == {"created": 1}
    assert reminders.scan(at) == {"created": 0}
    item = reminders.list()[0]
    assert item["kind"] == "due_soon" and item["task_id"] == task_id
    reminders.mark_read(item["id"])
    assert reminders.scan(at) == {"created": 0}
    assert reminders.scan(at + timedelta(hours=2)) == {"created": 1}
    assert reminders.list()[0]["kind"] == "overdue"
    with Session(engine) as s, s.begin():
        s.get(Task, task_id).due_at = at + timedelta(days=5)
    reminders.scan(at + timedelta(hours=2))
    assert reminders.list() == []
    with Session(engine) as s, s.begin():
        s.get(Task, task_id).due_at = at + timedelta(hours=3)
    assert reminders.scan(at + timedelta(hours=2)) == {"created": 1}
    with Session(engine) as s, s.begin():
        s.get(Task, task_id).status = "completed"
    assert reminders.scan(at + timedelta(hours=4)) == {"created": 0}
    assert reminders.list() == []
    with Session(engine) as s:
        assert len(list(s.scalars(select(Reminder)))) == 3


def test_historical_download_works_without_current_analysis(protocol, service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.protocols.dependencies import get_export_service
    from app.protocols.router import router

    saved = asyncio.run(service.export(protocol, "docx"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_export_service] = lambda: service
    with TestClient(app) as client:
        base = f"/api/v1/meetings/{protocol.meeting_id}/protocol-versions"
        history = client.get(base)
        assert history.status_code == 200 and len(history.json()) == 1
        snapshot = client.get(f"{base}/{saved.version_id}")
        assert snapshot.json()["title"] == protocol.title
        download = client.get(f"{base}/{saved.version_id}/exports/docx")
        assert download.status_code == 200 and download.content[:4] == b"PK\x03\x04"
        assert str(saved.version_id) in download.headers["content-disposition"]
        assert (
            client.get(
                f"/api/v1/meetings/{uuid4()}/protocol-versions/{saved.version_id}"
            ).status_code
            == 404
        )
