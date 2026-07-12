"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-11

Frozen DDL (alembic autogenerate output). Never derive this from the live
model metadata: create_all here once created a schema newer than revision
0001, which broke later migrations on fresh installs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("twitch_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login"),
        sa.UniqueConstraint("twitch_user_id"),
    )
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "capturing",
                "queued_transcription",
                "transcribing",
                "queued_analysis",
                "analyzing",
                "ready",
                "failed",
                name="stream_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("audit", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_streams_channel_id"), "streams", ["channel_id"], unique=False
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=True),
        sa.Column("author_id", sa.String(length=64), nullable=False),
        sa.Column("author_login", sa.String(length=64), nullable=False),
        sa.Column("badges", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("emotes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "text_search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('portuguese', text)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id", "sent_at"),
        postgresql_partition_by="RANGE (sent_at)",
    )
    op.create_index(
        "ix_chat_messages_stream_sent",
        "chat_messages",
        ["stream_id", "sent_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_text_search",
        "chat_messages",
        ["text_search"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_events_stream_occurred",
        "events",
        ["stream_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "summary",
                "peak_explanation",
                "topic",
                name="insight_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "feedback",
            sa.Enum("useful", "not_useful", name="insight_feedback", native_enum=False),
            nullable=True,
        ),
        sa.Column("model_used", sa.String(length=128), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_insights_stream_id"), "insights", ["stream_id"], unique=False
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "done",
                "failed",
                name="job_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_stream_id"), "jobs", ["stream_id"], unique=False)
    op.create_table(
        "peaks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_peaks_stream_id"), "peaks", ["stream_id"], unique=False)
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "speech",
                "music",
                "guest_conversation",
                "silence",
                name="segment_kind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "text_search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('portuguese', coalesce(text, ''))", persisted=True
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcript_segments_stream_started",
        "transcript_segments",
        ["stream_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_transcript_segments_text_search",
        "transcript_segments",
        ["text_search"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "viewer_samples",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("viewer_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_viewer_samples_stream_sampled",
        "viewer_samples",
        ["stream_id", "sampled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_viewer_samples_stream_sampled", table_name="viewer_samples")
    op.drop_table("viewer_samples")
    op.drop_index(
        "ix_transcript_segments_text_search", table_name="transcript_segments"
    )
    op.drop_index(
        "ix_transcript_segments_stream_started", table_name="transcript_segments"
    )
    op.drop_table("transcript_segments")
    op.drop_index(op.f("ix_peaks_stream_id"), table_name="peaks")
    op.drop_table("peaks")
    op.drop_index(op.f("ix_jobs_stream_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_insights_stream_id"), table_name="insights")
    op.drop_table("insights")
    op.drop_index("ix_events_stream_occurred", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_chat_messages_text_search", table_name="chat_messages")
    op.drop_index("ix_chat_messages_stream_sent", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_streams_channel_id"), table_name="streams")
    op.drop_table("streams")
    op.drop_table("channels")
