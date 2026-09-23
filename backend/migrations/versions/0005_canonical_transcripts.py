"""Canonical language artifacts, separate from Speech source-of-truth."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "canonical_transcripts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_audio_id",
            sa.Uuid(),
            sa.ForeignKey("normalized_audio.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_audio_id", "source_hash", "profile_hash", name="uq_canonical_source_profile"
        ),
    )


def downgrade():
    op.drop_table("canonical_transcripts")
