from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.infrastructure.database import Base, get_engine
from app.protocols.errors import ProtocolArtifactStorageError
from app.protocols.models import ExportedDocument


class ProtocolExportRecord(Base):
    __tablename__ = "protocol_exports"
    __table_args__ = (
        UniqueConstraint("meeting_id", "protocol_hash", "format", name="uq_protocol_export"),
    )
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("protocol_versions.id"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"), index=True)
    format: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(120))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    protocol_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def document(row):
    return ExportedDocument(**{name: getattr(row, name) for name in ExportedDocument.model_fields})


class ExportRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(bind=engine if engine is not None else get_engine())

    def save_version(self, protocol):
        from app.protocols.versions import save_version

        return save_version(self.sessions, protocol)

    def find(self, meeting_id, protocol_hash, format):
        try:
            with self.sessions() as s:
                row = s.scalar(
                    select(ProtocolExportRecord).where(
                        ProtocolExportRecord.meeting_id == meeting_id,
                        ProtocolExportRecord.protocol_hash == protocol_hash,
                        ProtocolExportRecord.format == format,
                    )
                )
                return document(row) if row else None
        except SQLAlchemyError:
            raise ProtocolArtifactStorageError from None

    def add_or_get(self, artifact):
        try:
            with self.sessions.begin() as s:
                s.add(ProtocolExportRecord(**artifact.model_dump()))
            return artifact
        except IntegrityError:
            saved = self.find(artifact.meeting_id, artifact.protocol_hash, artifact.format)
            if saved is not None:
                return saved
            raise ProtocolArtifactStorageError from None
        except SQLAlchemyError:
            raise ProtocolArtifactStorageError from None

    def remove(self, ident):
        try:
            with self.sessions.begin() as s:
                row = s.get(ProtocolExportRecord, ident)
                if row:
                    s.delete(row)
        except SQLAlchemyError:
            raise ProtocolArtifactStorageError from None
