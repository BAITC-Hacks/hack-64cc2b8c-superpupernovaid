from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.audio.errors import AudioPersistenceError
from app.audio.models import NormalizedAudio
from app.infrastructure.database import get_engine


class AudioRepository:
    def __init__(self, engine=None):
        self.sessions = sessionmaker(
            bind=engine if engine is not None else get_engine(), expire_on_commit=False
        )

    def find(self, media_id: UUID, config_hash: str) -> NormalizedAudio | None:
        try:
            with self.sessions() as session:
                return session.scalar(
                    select(NormalizedAudio).where(
                        NormalizedAudio.source_media_id == media_id,
                        NormalizedAudio.config_hash == config_hash,
                    )
                )
        except SQLAlchemyError as exc:
            raise AudioPersistenceError from exc

    def add_or_get(self, audio: NormalizedAudio) -> NormalizedAudio:
        try:
            with self.sessions.begin() as session:
                session.add(audio)
            return audio
        except IntegrityError as exc:
            # Concurrent processes can finish together: publish one result, discard the loser.
            existing = self.find(audio.source_media_id, audio.config_hash)
            if existing is not None:
                return existing
            raise AudioPersistenceError from exc
        except SQLAlchemyError as exc:
            raise AudioPersistenceError from exc

    def remove(self, audio_id: UUID) -> None:
        try:
            with self.sessions.begin() as session:
                session.execute(delete(NormalizedAudio).where(NormalizedAudio.id == audio_id))
        except SQLAlchemyError as exc:
            raise AudioPersistenceError from exc
