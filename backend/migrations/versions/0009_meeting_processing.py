"""Durable meeting processing runs.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meeting_processing_runs",
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meetings.id"), primary_key=True),
        sa.Column("id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("media_id", sa.Uuid(), sa.ForeignKey("media_assets.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30)),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("export_formats", sa.JSON(), nullable=False),
        sa.Column("exports", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("meeting_processing_runs")
