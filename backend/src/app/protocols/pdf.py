import asyncio
import hashlib
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, TableStyle

from app.protocols.errors import ProtocolDocumentRenderError
from app.protocols.models import MeetingProtocol, TextMode
from app.protocols.presentation import action_table, segment_heading, segment_text

_font_lock = Lock()


def text_markup(value):
    return escape(value).replace("\n", "<br/>")


class PdfProtocolRenderer:
    def __init__(self, font_path: Path, bold_font_path: Path, mode: TextMode = "canonical"):
        self.font_path, self.bold_font_path, self.mode = font_path, bold_font_path, mode

    @property
    def revision(self):
        try:
            digest = hashlib.sha256()
            for path in (self.font_path, self.bold_font_path):
                with path.open("rb") as stream:
                    while chunk := stream.read(65536):
                        digest.update(chunk)
            return "pdf-v1-" + self.mode + "-" + digest.hexdigest()
        except OSError:
            raise ProtocolDocumentRenderError from None

    async def render(self, protocol: MeetingProtocol, destination: Path) -> Path:
        try:
            await asyncio.to_thread(self._render, protocol, destination)
            return destination
        except Exception:
            raise ProtocolDocumentRenderError from None

    def _render(self, protocol, destination):
        font = "Qoryt-" + self.revision[-64:]
        bold = font + "-Bold"
        with _font_lock:
            if font not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font, str(self.font_path)))
                pdfmetrics.registerFont(TTFont(bold, str(self.bold_font_path)))
        # Fail explicitly instead of silently printing boxes for required RU/KZ glyphs.
        glyphs = pdfmetrics.getFont(font).face.charToGlyph
        if any(ord(c) not in glyphs for c in "ҚҒӘӨҰҮІҢқғәөұүіңРусский"):
            raise ProtocolDocumentRenderError
        normal = ParagraphStyle(
            "Normal",
            fontName=font,
            fontSize=10,
            leading=14,
            spaceAfter=7,
            alignment=TA_LEFT,
            splitLongWords=True,
        )
        title = ParagraphStyle(
            "Title",
            parent=normal,
            fontName=bold,
            fontSize=21,
            leading=27,
            spaceAfter=16,
            keepWithNext=True,
        )
        h1 = ParagraphStyle(
            "Heading1",
            parent=normal,
            fontName=bold,
            fontSize=14,
            leading=19,
            spaceBefore=12,
            keepWithNext=True,
        )
        h2 = ParagraphStyle(
            "Heading2", parent=normal, fontName=bold, fontSize=10, leading=14, keepWithNext=True
        )
        cell = ParagraphStyle("Cell", parent=normal, fontSize=8, leading=11, spaceAfter=0)
        elements = []

        def paragraph(text, style=normal):
            return Paragraph(text_markup(text), style)

        elements.extend(
            [paragraph("ПРОТОКОЛ СОВЕЩАНИЯ", title), paragraph("Название: " + protocol.title)]
        )
        if protocol.scheduled_at:
            elements.append(paragraph("Дата: " + protocol.scheduled_at.isoformat()))
        if protocol.participants:
            elements.append(paragraph("Участники", h1))
            elements.extend(
                paragraph("• " + (p.participant_name or p.speaker_id))
                for p in protocol.participants
            )
        if protocol.summary:
            elements.extend([paragraph("КРАТКОЕ СОДЕРЖАНИЕ", h1), paragraph(protocol.summary)])
        for label, values in [
            ("ОСНОВНЫЕ ТЕМЫ", protocol.topics),
            ("ПРИНЯТЫЕ РЕШЕНИЯ", tuple(x.text for x in protocol.decisions)),
        ]:
            if values:
                elements.append(paragraph(label, h1))
                elements.extend(paragraph(f"{i}. {value}") for i, value in enumerate(values, 1))
        if protocol.action_items:
            elements.append(paragraph("ПОРУЧЕНИЯ", h1))
            header, rows = action_table(protocol)
            data = [[paragraph(t, cell) for t in row] for row in [header, *rows]]
            widths = [0.8, 6.2, 3.4, 3.3, 3.3] if len(header) == 5 else [0.8, 8, 4, 4.2]
            table = LongTable(
                data, colWidths=[w * cm for w in widths], repeatRows=1, splitByRow=1, splitInRow=1
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEFF2")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            elements.append(table)
        if protocol.transcript:
            elements.extend([PageBreak(), paragraph("СТЕНОГРАММА", h1)])
            for seg in protocol.transcript:
                elements.extend(
                    [paragraph(segment_heading(seg), h2), paragraph(segment_text(seg, self.mode))]
                )

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont(font, 8)
            canvas.drawRightString(A4[0] - 2 * cm, cm, str(doc.page))
            canvas.restoreState()

        doc = SimpleDocTemplate(
            str(destination),
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=protocol.title,
            author="Qoryt",
        )
        doc.build(elements, onFirstPage=footer, onLaterPages=footer)
