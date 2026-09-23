from alembic import context
from sqlalchemy import create_engine

from app.audio import models as audio_models  # noqa: F401
from app.config import get_settings
from app.infrastructure.database import Base
from app.media import models  # noqa: F401 — register media tables for autogenerate

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
