import shutil
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.meetings.schemas import Input
from app.protocols.dependencies import get_export_service, get_protocol_loader
from app.protocols.errors import ProtocolExportError
from app.protocols.loader import ProtocolLoader
from app.protocols.models import MIME_TYPES, ExportedDocument, ExportFormat, MeetingProtocol
from app.protocols.service import ProtocolExportService
from app.protocols.versions import ProtocolVersion, VersionView, load_version


class ExportFileResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also runs if the client disconnects or sending raises.
            shutil.rmtree(self.path.parent, ignore_errors=True)


class ExportRequest(Input):
    format: ExportFormat


router = APIRouter(prefix="/api/v1/meetings", tags=["Protocols"])
Loader = Annotated[ProtocolLoader, Depends(get_protocol_loader)]
Service = Annotated[ProtocolExportService, Depends(get_export_service)]
ERRORS = {
    404: {"description": "Meeting not found"},
    409: {"description": "Protocol not ready"},
    413: {"description": "Export too large"},
    422: {"description": "Unsupported format or rendering failure"},
    429: {"description": "Export capacity busy"},
    503: {"description": "Artifact unavailable"},
}


def http_error(exc):
    return HTTPException(
        exc.http_status,
        {"code": exc.code, "message": exc.message},
        headers={"Retry-After": "5"} if exc.http_status == 429 else None,
    )


@router.post("/{meeting_id}/exports", response_model=ExportedDocument, responses=ERRORS)
async def export_protocol(
    meeting_id: UUID, payload: ExportRequest, loader: Loader, service: Service
):
    try:
        protocol = await run_in_threadpool(loader.load, meeting_id)
        return await service.export(protocol, payload.format)
    except ProtocolExportError as exc:
        raise http_error(exc) from None


@router.get(
    "/{meeting_id}/exports/{format}",
    response_class=FileResponse,
    responses={
        200: {
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in MIME_TYPES.values()
            }
        },
        **ERRORS,
    },
)
async def download_protocol(
    meeting_id: UUID, format: ExportFormat, loader: Loader, service: Service
):
    try:
        protocol = await run_in_threadpool(loader.load, meeting_id)
        artifact = await service.export(protocol, format)
        path = await run_in_threadpool(service.prepare_download, artifact)
        return ExportFileResponse(
            path,
            media_type=MIME_TYPES[format],
            filename=artifact.filename,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    except ProtocolExportError as exc:
        raise http_error(exc) from None


@router.get("/{meeting_id}/protocol-versions", response_model=list[VersionView])
def list_protocol_versions(
    meeting_id: UUID,
    service: Service,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        with service.repository.sessions() as session:
            return [
                VersionView.model_validate(row)
                for row in session.scalars(
                    select(ProtocolVersion)
                    .where(ProtocolVersion.meeting_id == meeting_id)
                    .order_by(ProtocolVersion.created_at.desc(), ProtocolVersion.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ]
    except SQLAlchemyError:
        raise HTTPException(503, "Protocol history unavailable") from None


@router.get("/{meeting_id}/protocol-versions/{version_id}", response_model=MeetingProtocol)
def get_protocol_version(meeting_id: UUID, version_id: UUID, service: Service):
    try:
        return load_version(service.repository.sessions, meeting_id, version_id)
    except ProtocolExportError as exc:
        raise http_error(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Protocol history unavailable") from None


@router.get(
    "/{meeting_id}/protocol-versions/{version_id}/exports/{format}", response_class=FileResponse
)
async def download_protocol_version(
    meeting_id: UUID, version_id: UUID, format: ExportFormat, service: Service
):
    try:
        protocol = await run_in_threadpool(
            load_version, service.repository.sessions, meeting_id, version_id
        )
        artifact = await service.export(protocol, format)
        path = await run_in_threadpool(service.prepare_download, artifact)
        return ExportFileResponse(
            path,
            media_type=MIME_TYPES[format],
            filename=f"meeting_{meeting_id}_version_{version_id}.{format}",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    except ProtocolExportError as exc:
        raise http_error(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Protocol history unavailable") from None
