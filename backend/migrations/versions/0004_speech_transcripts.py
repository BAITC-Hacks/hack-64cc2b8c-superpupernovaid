"""Persist attributed transcripts and stable segment IDs."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "speech_transcripts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_audio_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_audio.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_audio_id", "profile_hash", name="uq_speech_profile"),
    )


def downgrade():
    op.drop_table("speech_transcripts")
