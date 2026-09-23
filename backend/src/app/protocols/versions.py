"""Immutable protocol content, independently of renderer/layout revisions."""

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base
from app.meetings.models import now
from app.protocols.errors import ProtocolExportError
from app.protocols.models import MeetingProtocol


class ProtocolVersion(Base):
    __tablename__ = "protocol_versions"
    __table_args__ = (UniqueConstraint("meeting_id", "content_hash", name="uq_protocol_version"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    meeting_id: UUID
    content_hash: str
    created_at: datetime


def save_version(sessions, protocol: MeetingProtocol) -> VersionView:
    payload = protocol.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    query = select(ProtocolVersion).where(
        ProtocolVersion.meeting_id == protocol.meeting_id, ProtocolVersion.content_hash == digest
    )
    with sessions() as session:
        existing = session.scalar(query)
        if existing:
            return VersionView.model_validate(existing)
    try:
        with sessions.begin() as session:
            row = ProtocolVersion(
                meeting_id=protocol.meeting_id, content_hash=digest, payload=payload
            )
            session.add(row)
            session.flush()
            result = VersionView.model_validate(row)
        return result
    except IntegrityError:
        with sessions() as session:
            existing = session.scalar(query)
            if existing is None:
                raise
            return VersionView.model_validate(existing)


def load_version(sessions, meeting_id, version_id):
    with sessions() as session:
        row = session.get(ProtocolVersion, version_id)
        if row is None or row.meeting_id != meeting_id:
            raise HTTPException(404, "Protocol version not found")
        digest = hashlib.sha256(
            json.dumps(
                row.payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if digest != row.content_hash:
            raise ProtocolExportError
        return MeetingProtocol.model_validate(row.payload)
