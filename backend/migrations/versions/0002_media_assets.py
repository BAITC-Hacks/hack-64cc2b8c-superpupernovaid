"""Persist original meeting media references and inspection metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(10), nullable=False),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("container", sa.String(100), nullable=False),
        sa.Column("audio_codec", sa.String(100)),
        sa.Column("video_codec", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_media_assets_positive_size"),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="ck_media_assets_duration"
        ),
        sa.CheckConstraint("media_type IN ('audio', 'video')", name="ck_media_assets_type"),
        sa.CheckConstraint("status IN ('uploaded', 'invalid')", name="ck_media_assets_status"),
    )
    op.create_index("ix_media_assets_meeting_id", "media_assets", ["meeting_id"])


def downgrade():
    op.drop_index("ix_media_assets_meeting_id", table_name="media_assets")
    op.drop_table("media_assets")
