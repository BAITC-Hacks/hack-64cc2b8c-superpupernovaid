"""Immutable protocol content and database-only task reminders."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "protocol_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("meeting_id", "content_hash", name="uq_protocol_version"),
    )
    op.create_index("ix_protocol_versions_meeting_id", "protocol_versions", ["meeting_id"])
    with op.batch_alter_table("protocol_exports") as batch:
        batch.add_column(sa.Column("version_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_export_version", "protocol_versions", ["version_id"], ["id"])
    op.create_table(
        "task_reminders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("meeting_tasks.id"), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), sa.ForeignKey("meeting_participants.id")),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    for column in ("task_id", "meeting_id", "status"):
        op.create_index("ix_task_reminders_" + column, "task_reminders", [column])


def downgrade():
    op.drop_table("task_reminders")
    with op.batch_alter_table("protocol_exports") as batch:
        batch.drop_constraint("fk_export_version", type_="foreignkey")
        batch.drop_column("version_id")
    op.drop_table("protocol_versions")
