from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import get_engine
from app.media.errors import MediaPersistenceError
from app.media.models import MediaAsset


class MediaRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(
            bind=engine if engine is not None else get_engine(), expire_on_commit=False
        )

    def add(self, asset: MediaAsset) -> None:
        try:
            with self.sessions.begin() as session:
                session.add(asset)
        except SQLAlchemyError as exc:
            raise MediaPersistenceError from exc

    def get(self, meeting_id: UUID, media_id: UUID) -> MediaAsset | None:
        try:
            with self.sessions() as session:
                asset = session.get(MediaAsset, media_id)
                return asset if asset is not None and asset.meeting_id == meeting_id else None
        except SQLAlchemyError as exc:
            raise MediaPersistenceError from exc
