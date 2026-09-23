import asyncio
import shutil

import pytest
from sqlalchemy import create_engine

from app.infrastructure.database import Base
from app.media.storage import LocalMediaStorage
from app.protocols.docx import DocxProtocolRenderer
from app.protocols.errors import (
    ProtocolExportBusyError,
    ProtocolExportTooLargeError,
    UnsupportedExportFormatError,
)
from app.protocols.repository import ExportRepository
from app.protocols.service import ProtocolExportService


@pytest.fixture
def service(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "db.sqlite"))
    # Register all FK targets without running application lifespan or external models.
    from app.entrypoints.api import app  # noqa: F401

    Base.metadata.create_all(engine)
    return ProtocolExportService(
        {"docx": DocxProtocolRenderer()},
        LocalMediaStorage(tmp_path / "storage"),
        ExportRepository(engine),
    )


def test_idempotency_changes_repair_and_safe_filename(protocol, service):
    async def run():
        first = await service.export(protocol, "docx")
        second = await service.export(protocol, "docx")
        assert first.id == second.id and first.storage_key == second.storage_key
        modified = protocol.model_copy(update={"title": "../../unsafe/title"})
        third = await service.export(modified, "docx")
        assert third.id != first.id and ".." not in third.filename and "/" not in third.filename
        path = service.prepare_download(first)
        assert path.stat().st_size == first.size_bytes
        shutil.rmtree(path.parent)
        service.storage.delete(first.storage_key)
        repaired = await service.export(protocol, "docx")
        assert repaired.id != first.id
        assert len(list(service.storage.root.rglob("*.docx"))) == 2

    asyncio.run(run())


def test_limits_and_unsupported(protocol, service):
    with pytest.raises(UnsupportedExportFormatError):
        asyncio.run(service.export(protocol, "html"))
    service.max_characters = 5
    with pytest.raises(ProtocolExportTooLargeError):
        asyncio.run(service.export(protocol, "docx"))
    assert not service.storage.root.exists()


def test_disconnect_does_not_release_capacity(protocol, service):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        real = service.renderers["docx"]

        class Slow:
            revision = real.revision

            async def render(self, p, path):
                entered.set()
                await release.wait()
                return await real.render(p, path)

        service.renderers["docx"] = Slow()
        call = asyncio.create_task(service.export(protocol, "docx"))
        await entered.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        with pytest.raises(ProtocolExportBusyError):
            await service.export(protocol, "docx")
        release.set()
        await service.close()
        assert len(list(service.storage.root.rglob("*.docx"))) == 1

    asyncio.run(run())


def test_corrupt_artifact_repaired_and_download_failure_cleaned(
    protocol, service, tmp_path, monkeypatch
):
    import app.protocols.service as module
    from app.protocols.errors import ProtocolArtifactStorageError

    first = asyncio.run(service.export(protocol, "docx"))
    (service.storage.root / first.storage_key).write_bytes(b"broken")
    folder = tmp_path / "download"
    folder.mkdir()
    monkeypatch.setattr(module, "mkdtemp", lambda **_: str(folder))
    with pytest.raises(ProtocolArtifactStorageError):
        service.prepare_download(first)
    assert not folder.exists()
    repaired = asyncio.run(service.export(protocol, "docx"))
    assert repaired.id != first.id
    assert len(list(service.storage.root.rglob("*.docx"))) == 1


def test_download_response_cleans_on_disconnect(tmp_path):
    from app.protocols.router import ExportFileResponse

    folder = tmp_path / "download"
    folder.mkdir()
    path = folder / "test.pdf"
    path.write_bytes(b"%PDF-example")

    async def send(_):
        raise OSError("client disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(OSError):
        asyncio.run(
            ExportFileResponse(path)(
                {"type": "http", "method": "GET", "headers": [], "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )
        )
    assert not folder.exists()
