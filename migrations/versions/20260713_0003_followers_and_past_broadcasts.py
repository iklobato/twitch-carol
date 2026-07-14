"""followers and past broadcasts

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "followers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("twitch_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("followed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_followers_channel_id", "followers", ["channel_id"])
    op.create_index(
        "uq_followers_channel_user",
        "followers",
        ["channel_id", "twitch_user_id"],
        unique=True,
    )

    op.create_table(
        "past_broadcasts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("twitch_video_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=256), nullable=False),
    )
    op.create_index("ix_past_broadcasts_channel_id", "past_broadcasts", ["channel_id"])
    op.create_index(
        "uq_past_broadcasts_channel_video",
        "past_broadcasts",
        ["channel_id", "twitch_video_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("past_broadcasts")
    op.drop_table("followers")
