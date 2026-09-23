"""Agent artifacts and explicit task provenance, after protocol exports."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meeting_analyses", sa.Column("details", sa.JSON(), nullable=True))
    op.create_table(
        "agent_analysis_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
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
            "meeting_id",
            "source_audio_id",
            "source_hash",
            "profile_hash",
            name="uq_meeting_analysis_source_profile",
        ),
    )
    op.create_index(
        "ix_agent_analysis_artifacts_meeting_id", "agent_analysis_artifacts", ["meeting_id"]
    )

    op.create_table(
        "speaker_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
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
            "meeting_id",
            "source_audio_id",
            "source_hash",
            "profile_hash",
            name="uq_speaker_mapping_source_profile",
        ),
    )
    op.create_index("ix_speaker_mappings_meeting_id", "speaker_mappings", ["meeting_id"])

    op.add_column(
        "meeting_tasks", sa.Column("origin", sa.String(10), nullable=False, server_default="manual")
    )
    # Historical manual creation has an audit row, even when linked to a transcript.
    op.execute("""UPDATE meeting_tasks SET origin = 'generated'
        WHERE transcript_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM meeting_change_audit a
          WHERE a.entity_id = meeting_tasks.id AND a.action = 'task.create')""")


def downgrade():
    op.drop_column("meeting_analyses", "details")
    op.drop_column("meeting_tasks", "origin")
    op.drop_index("ix_speaker_mappings_meeting_id", table_name="speaker_mappings")
    op.drop_table("speaker_mappings")

    op.drop_index("ix_agent_analysis_artifacts_meeting_id", table_name="agent_analysis_artifacts")
    op.drop_table("agent_analysis_artifacts")
