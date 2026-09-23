"""Register canonical audio artifacts and idempotency keys."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "normalized_audio",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_media_id", sa.Uuid(), sa.ForeignKey("media_assets.id"), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), unique=True, nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("codec", sa.String(32), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_media_id", "config_hash", name="uq_audio_source_config"),
        sa.CheckConstraint("size_bytes > 0 AND duration_seconds > 0", name="ck_audio_nonempty"),
        sa.CheckConstraint("sample_rate > 0 AND channels > 0", name="ck_audio_parameters"),
    )


def downgrade():
    op.drop_table("normalized_audio")
