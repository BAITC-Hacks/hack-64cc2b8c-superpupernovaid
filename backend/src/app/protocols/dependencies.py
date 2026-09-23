from functools import lru_cache

from app.bootstrap import get_media_storage
from app.config import get_settings
from app.protocols.docx import DocxProtocolRenderer
from app.protocols.loader import ProtocolLoader
from app.protocols.pdf import PdfProtocolRenderer
from app.protocols.repository import ExportRepository
from app.protocols.service import ProtocolExportService


@lru_cache
def get_protocol_loader():
    return ProtocolLoader()


@lru_cache
def get_export_service():
    s = get_settings()
    return ProtocolExportService(
        {
            "docx": DocxProtocolRenderer(s.protocol_transcript_text_mode),
            "pdf": PdfProtocolRenderer(
                s.protocol_pdf_font_path,
                s.protocol_pdf_bold_font_path,
                s.protocol_transcript_text_mode,
            ),
        },
        get_media_storage(),
        ExportRepository(),
        s.protocol_export_max_characters,
        s.protocol_export_max_bytes,
    )


async def shutdown_exports():
    if get_export_service.cache_info().currsize:
        await get_export_service().close()
    get_export_service.cache_clear()
    get_protocol_loader.cache_clear()
