"""vips and goals

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vips",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("twitch_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_vips_channel_id", "vips", ["channel_id"])
    op.create_index(
        "uq_vips_channel_user", "vips", ["channel_id", "twitch_user_id"], unique=True
    )

    op.create_table(
        "goals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("twitch_goal_id", sa.String(length=64), nullable=False),
        sa.Column("goal_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("current_amount", sa.Integer(), nullable=False),
        sa.Column("target_amount", sa.Integer(), nullable=False),
    )
    op.create_index("ix_goals_channel_id", "goals", ["channel_id"])
    op.create_index(
        "uq_goals_channel_twitch",
        "goals",
        ["channel_id", "twitch_goal_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("goals")
    op.drop_table("vips")
