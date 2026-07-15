"""Database models. All timestamps are UTC (timestamptz)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StreamStatus(enum.StrEnum):
    CAPTURING = "capturing"
    QUEUED_TRANSCRIPTION = "queued_transcription"
    TRANSCRIBING = "transcribing"
    QUEUED_ANALYSIS = "queued_analysis"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"


class SegmentKind(enum.StrEnum):
    SPEECH = "speech"
    MUSIC = "music"
    GUEST_CONVERSATION = "guest_conversation"
    SILENCE = "silence"


class InsightType(enum.StrEnum):
    SUMMARY = "summary"
    PEAK_EXPLANATION = "peak_explanation"
    TOPIC = "topic"
    RECOMMENDATION = "recommendation"


class InsightFeedback(enum.StrEnum):
    USEFUL = "useful"
    NOT_USEFUL = "not_useful"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in enum_cls]


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # VARCHAR + CHECK constraint instead of a native pg enum: adding members
    # later is a plain migration, not an ALTER TYPE dance.
    return Enum(enum_cls, name=name, native_enum=False, values_callable=_enum_values)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    twitch_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    access_token_encrypted: Mapped[bytes | None]
    refresh_token_encrypted: Mapped[bytes | None]
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Follower(Base):
    """Channel-level follower state. Seeded from Helix on connect (with real
    followed_at) and kept fresh by the live channel.follow event."""

    __tablename__ = "followers"
    __table_args__ = (
        Index("uq_followers_channel_user", "channel_id", "twitch_user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    twitch_user_id: Mapped[int] = mapped_column(BigInteger)
    login: Mapped[str] = mapped_column(String(64))
    followed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Enrichment from Helix Get Users, filled on connect. enriched_at is NULL
    # until the first enrichment, so a partial backfill can be resumed.
    display_name: Mapped[str | None] = mapped_column(String(128))
    profile_image_url: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    broadcaster_type: Mapped[str | None] = mapped_column(String(16))
    account_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PastBroadcast(Base):
    """A past VOD pulled from Helix on connect. Kept apart from Stream because
    VODs carry total-view counts, not the concurrent-viewer/chat timeline that
    the analytics run on."""

    __tablename__ = "past_broadcasts"
    __table_args__ = (
        Index(
            "uq_past_broadcasts_channel_video",
            "channel_id",
            "twitch_video_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    twitch_video_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int]
    view_count: Mapped[int]
    url: Mapped[str] = mapped_column(String(256))


class Vip(Base):
    """Channel VIPs, seeded from Helix on connect."""

    __tablename__ = "vips"
    __table_args__ = (
        Index("uq_vips_channel_user", "channel_id", "twitch_user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    twitch_user_id: Mapped[int] = mapped_column(BigInteger)
    login: Mapped[str] = mapped_column(String(64))


class Goal(Base):
    """Current creator goal snapshot (follower/sub/etc), seeded on connect."""

    __tablename__ = "goals"
    __table_args__ = (
        Index("uq_goals_channel_twitch", "channel_id", "twitch_goal_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    twitch_goal_id: Mapped[str] = mapped_column(String(64))
    goal_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(String(256))
    current_amount: Mapped[int]
    target_amount: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    """Current subscriber snapshot from Helix (affiliate/partner only), seeded
    on connect. Churn is derived separately from channel.subscription.end."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index(
            "uq_subscriptions_channel_user",
            "channel_id",
            "twitch_user_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    twitch_user_id: Mapped[int] = mapped_column(BigInteger)
    login: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(8))
    is_gift: Mapped[bool] = mapped_column(default=False)
    gifter_login: Mapped[str | None] = mapped_column(String(64))


class BitsLeader(Base):
    """All-time bits leaderboard snapshot from Helix (affiliate only)."""

    __tablename__ = "bits_leaders"
    __table_args__ = (Index("ix_bits_leaders_channel_rank", "channel_id", "rank"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    login: Mapped[str] = mapped_column(String(64))
    rank: Mapped[int]
    score: Mapped[int]


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(String(256))
    category: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[StreamStatus] = mapped_column(
        _enum(StreamStatus, "stream_status"), default=StreamStatus.CAPTURING
    )
    audit: Mapped[dict | None] = mapped_column(JSONB)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_stream_sent", "stream_id", "sent_at"),
        Index("ix_chat_messages_text_search", "text_search", postgresql_using="gin"),
        {"postgresql_partition_by": "RANGE (sent_at)"},
    )

    # Partitioned by month on sent_at, so the partition key joins the PK.
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    message_id: Mapped[str | None] = mapped_column(String(64))
    author_id: Mapped[str] = mapped_column(String(64))
    author_login: Mapped[str] = mapped_column(String(64))
    badges: Mapped[dict | None] = mapped_column(JSONB)
    emotes: Mapped[dict | None] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)
    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('portuguese', text)", persisted=True)
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_stream_occurred", "stream_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    amount: Mapped[int | None]


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        Index("ix_transcript_segments_stream_started", "stream_id", "started_at"),
        Index(
            "ix_transcript_segments_text_search", "text_search", postgresql_using="gin"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[SegmentKind] = mapped_column(_enum(SegmentKind, "segment_kind"))
    text: Mapped[str | None] = mapped_column(Text)
    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('portuguese', coalesce(text, ''))", persisted=True),
    )


class ViewerSample(Base):
    __tablename__ = "viewer_samples"
    __table_args__ = (
        Index("ix_viewer_samples_stream_sampled", "stream_id", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    viewer_count: Mapped[int]


class Peak(Base):
    __tablename__ = "peaks"

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metric: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    type: Mapped[InsightType] = mapped_column(_enum(InsightType, "insight_type"))
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    feedback: Mapped[InsightFeedback | None] = mapped_column(
        _enum(InsightFeedback, "insight_feedback")
    )
    model_used: Mapped[str] = mapped_column(String(128))
    tokens_in: Mapped[int]
    tokens_out: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChannelRecommendation(Base):
    """Account-level monetization advice from the LLM, grounded in the numbered
    SQL facts it cited. Regenerated as a set, not per-stream like Insight."""

    __tablename__ = "channel_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    model_used: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FollowerRecommendation(Base):
    """Account-level advice about the follower base (reactivation, collab, fake-
    follow risk, content/timing), grounded in numbered SQL facts. Regenerated as
    a set, mirroring ChannelRecommendation."""

    __tablename__ = "follower_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    model_used: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
