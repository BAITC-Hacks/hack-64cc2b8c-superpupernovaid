import shutil
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.meetings.schemas import Input
from app.protocols.dependencies import get_export_service, get_protocol_loader
from app.protocols.errors import ProtocolExportError
from app.protocols.loader import ProtocolLoader
from app.protocols.models import MIME_TYPES, ExportedDocument, ExportFormat
from app.protocols.service import ProtocolExportService


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
