"""add meeting workspace and task contracts"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("processing_status", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language_hint", sa.String(length=10), nullable=False),
        sa.Column("expected_participant_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meetings_processing_status"), "meetings", ["processing_status"], unique=False
    )
    op.create_table(
        "meeting_change_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meeting_change_audit_meeting_id"),
        "meeting_change_audit",
        ["meeting_id"],
        unique=False,
    )
    op.create_table(
        "meeting_recording_consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meeting_recording_consents_meeting_id"),
        "meeting_recording_consents",
        ["meeting_id"],
        unique=False,
    )
    op.create_table(
        "meeting_processing_steps",
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media_assets.id"],
        ),
        sa.PrimaryKeyConstraint("media_id", "stage"),
    )
    op.create_table(
        "meeting_analyses",
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["speech_transcripts.id"],
        ),
        sa.PrimaryKeyConstraint("transcript_id"),
    )
    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("speaker_id", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["speech_transcripts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "speaker_id", name="uq_participant_speaker"),
    )
    op.create_index(
        op.f("ix_meeting_participants_meeting_id"),
        "meeting_participants",
        ["meeting_id"],
        unique=False,
    )
    op.create_table(
        "meeting_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_segment_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["meeting_analyses.transcript_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meeting_decisions_transcript_id"),
        "meeting_decisions",
        ["transcript_id"],
        unique=False,
    )
    op.create_table(
        "meeting_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False),
        sa.Column("source_segment_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["meeting_participants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["speech_transcripts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meeting_tasks_due_at"), "meeting_tasks", ["due_at"], unique=False)
    op.create_index(
        op.f("ix_meeting_tasks_meeting_id"), "meeting_tasks", ["meeting_id"], unique=False
    )
    op.create_index(op.f("ix_meeting_tasks_status"), "meeting_tasks", ["status"], unique=False)
    backfill()
    with op.batch_alter_table("media_assets") as batch:
        batch.create_foreign_key("fk_media_meeting", "meetings", ["meeting_id"], ["id"])


def downgrade():
    # WARNING: constraint name is None; this directive will fail as
    # rendered.  Add a name, or use a naming convention; see
    # https://alembic.sqlalchemy.org/en/latest/naming.html
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_constraint("fk_media_meeting", type_="foreignkey")
    op.drop_index(op.f("ix_meeting_tasks_status"), table_name="meeting_tasks")
    op.drop_index(op.f("ix_meeting_tasks_meeting_id"), table_name="meeting_tasks")
    op.drop_index(op.f("ix_meeting_tasks_due_at"), table_name="meeting_tasks")
    op.drop_table("meeting_tasks")
    op.drop_index(op.f("ix_meeting_decisions_transcript_id"), table_name="meeting_decisions")
    op.drop_table("meeting_decisions")
    op.drop_index(op.f("ix_meeting_participants_meeting_id"), table_name="meeting_participants")
    op.drop_table("meeting_participants")
    op.drop_table("meeting_analyses")
    op.drop_table("meeting_processing_steps")
    op.drop_index(
        op.f("ix_meeting_recording_consents_meeting_id"), table_name="meeting_recording_consents"
    )
    op.drop_table("meeting_recording_consents")
    op.drop_index(op.f("ix_meeting_change_audit_meeting_id"), table_name="meeting_change_audit")
    op.drop_table("meeting_change_audit")
    op.drop_index(op.f("ix_meetings_processing_status"), table_name="meetings")
    op.drop_table("meetings")


def backfill():
    # Preserve every old media UUID; never invent consent for historical recordings.
    from datetime import UTC, datetime
    from uuid import uuid4

    bind = op.get_bind()
    metadata = sa.MetaData()
    tables = {
        name: sa.Table(name, metadata, autoload_with=bind)
        for name in (
            "meetings",
            "meeting_recording_consents",
            "media_assets",
            "normalized_audio",
            "speech_transcripts",
            "meeting_participants",
        )
    }
    m, c, media, audio, speech, participant = tables.values()

    def new_id():
        return uuid4().hex if bind.dialect.name == "sqlite" else uuid4()

    seen = set()
    for row in bind.execute(
        sa.select(media).order_by(media.c.created_at.desc(), media.c.id.desc())
    ).mappings():
        if row["meeting_id"] in seen:
            continue
        seen.add(row["meeting_id"])
        has_audio = bind.scalar(
            sa.select(audio.c.id).where(audio.c.source_media_id == row["id"]).limit(1)
        )
        has_speech = bind.scalar(
            sa.select(speech.c.id)
            .join(audio, speech.c.source_audio_id == audio.c.id)
            .where(audio.c.source_media_id == row["id"])
            .limit(1)
        )
        bind.execute(
            m.insert().values(
                id=row["meeting_id"],
                title=row["original_filename"],
                processing_status="analyzing"
                if has_speech
                else ("transcribing" if has_audio else "uploaded"),
                language_hint="auto",
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
        bind.execute(
            c.insert().values(
                id=new_id(),
                meeting_id=row["meeting_id"],
                confirmed=False,
                source="legacy_unknown",
                created_at=datetime.now(UTC),
            )
        )
    query = (
        sa.select(speech.c.id, speech.c.payload, media.c.meeting_id)
        .join(audio, speech.c.source_audio_id == audio.c.id)
        .join(media, audio.c.source_media_id == media.c.id)
    )
    for row in bind.execute(query).mappings():
        labels = {seg["speaker_id"] for seg in row["payload"]["segments"]} - {"UNKNOWN"}
        for label in labels:
            bind.execute(
                participant.insert().values(
                    id=new_id(),
                    meeting_id=row["meeting_id"],
                    transcript_id=row["id"],
                    speaker_id=label,
                )
            )
