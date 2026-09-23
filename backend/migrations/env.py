from alembic import context
from sqlalchemy import create_engine

from app.audio import models as audio_models  # noqa: F401
from app.canonicalization import repository as canonical_repository  # noqa: F401
from app.config import get_settings
from app.infrastructure.database import Base
from app.intelligence import models as intelligence_models  # noqa: F401
from app.intelligence.pipeline import repository, speaker_repository  # noqa: F401
from app.media import models  # noqa: F401 — register media tables for autogenerate
from app.meetings import models as meeting_models  # noqa: F401
from app.processing import models as processing_models  # noqa: F401
from app.protocols import repository as protocol_repository  # noqa: F401
from app.speech import repository as speech_repository  # noqa: F401
from app.tasks import models as task_models  # noqa: F401

if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
