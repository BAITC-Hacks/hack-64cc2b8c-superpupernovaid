"""Reusable protocol export artifact references."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "protocol_exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("protocol_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("meeting_id", "protocol_hash", "format", name="uq_protocol_export"),
    )
    op.create_index("ix_protocol_exports_meeting_id", "protocol_exports", ["meeting_id"])


def downgrade():
    op.drop_index("ix_protocol_exports_meeting_id", table_name="protocol_exports")
    op.drop_table("protocol_exports")
