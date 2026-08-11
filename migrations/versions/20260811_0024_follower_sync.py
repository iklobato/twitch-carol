"""follower sync state, last_seen marker and the unfollows table

Numbered 0024 on purpose, leaving 0023 free: two other branches already claim it
(chat_channel_index and backfill_canais_existentes), and all three hang off 0022.
Whichever of them merges first, the next one has to repoint its down_revision or
alembic ends up with several heads and `upgrade head` refuses to run.

Revision ID: 0024
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0022"
branch_labels: str | None = None
depends_on: str | None = None

UNFOLLOW_REASON = "unfollow_reason"


def upgrade() -> None:
    op.add_column("channels", sa.Column("follower_total", sa.Integer(), nullable=True))
    op.add_column(
        "channels",
        sa.Column("followers_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "channels", sa.Column("follower_sync_cursor", sa.String(512), nullable=True)
    )
    op.add_column(
        "channels",
        sa.Column(
            "follower_sync_started_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "channels", sa.Column("follower_sync_error", sa.Text(), nullable=True)
    )
    op.add_column(
        "followers",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # native_enum=False to match the rest of the schema: VARCHAR + CHECK, so
    # adding a reason later is a plain migration instead of an ALTER TYPE.
    reason = sa.Enum(
        "unfollowed", "account_gone", name=UNFOLLOW_REASON, native_enum=False
    )
    op.create_table(
        "unfollows",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("twitch_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("profile_image_url", sa.String(256), nullable=True),
        sa.Column("followed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", reason, nullable=False),
    )
    op.create_index("ix_unfollows_channel_id", "unfollows", ["channel_id"])
    # followers_synced_at is left NULL for every existing channel, which is what
    # the worker treats as "sync me first". No data is written here: the real
    # totals have to come from Twitch, and one production channel is currently
    # 21,605 followers short of its own.


def downgrade() -> None:
    op.drop_index("ix_unfollows_channel_id", table_name="unfollows")
    op.drop_table("unfollows")
    op.drop_column("followers", "last_seen_at")
    op.drop_column("channels", "follower_sync_error")
    op.drop_column("channels", "follower_sync_started_at")
    op.drop_column("channels", "follower_sync_cursor")
    op.drop_column("channels", "followers_synced_at")
    op.drop_column("channels", "follower_total")
