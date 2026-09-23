from pathlib import Path
from typing import Protocol

from app.protocols.models import MeetingProtocol


class ProtocolRenderer(Protocol):
    @property
    def revision(self) -> str: ...

    async def render(self, protocol: MeetingProtocol, destination: Path) -> Path: ...
