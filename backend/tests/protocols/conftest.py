import os
from pathlib import Path

import pytest

from app.protocols.pdf import PdfProtocolRenderer

from .fixtures import golden_protocol


@pytest.fixture
def protocol():
    return golden_protocol()


@pytest.fixture
def pdf_renderer():
    default = Path("/usr/share/fonts/truetype/dejavu")
    root = Path(os.getenv("PROTOCOL_TEST_FONT_DIR", str(default)))
    if not (root / "DejaVuSans.ttf").is_file():
        pytest.fail("Install fonts-dejavu-core or set PROTOCOL_TEST_FONT_DIR to DejaVu fonts")
    return PdfProtocolRenderer(root / "DejaVuSans.ttf", root / "DejaVuSans-Bold.ttf")
