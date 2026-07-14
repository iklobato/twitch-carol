"""subscriptions and bits leaders

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("twitch_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.String(length=8), nullable=False),
        sa.Column("is_gift", sa.Boolean(), nullable=False),
        sa.Column("gifter_login", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_subscriptions_channel_id", "subscriptions", ["channel_id"])
    op.create_index(
        "uq_subscriptions_channel_user",
        "subscriptions",
        ["channel_id", "twitch_user_id"],
        unique=True,
    )

    op.create_table(
        "bits_leaders",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
    )
    op.create_index("ix_bits_leaders_channel_id", "bits_leaders", ["channel_id"])
    op.create_index(
        "ix_bits_leaders_channel_rank", "bits_leaders", ["channel_id", "rank"]
    )


def downgrade() -> None:
    op.drop_table("bits_leaders")
    op.drop_table("subscriptions")
