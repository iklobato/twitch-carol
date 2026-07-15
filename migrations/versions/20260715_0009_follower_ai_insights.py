"""follower ai insights

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "follower_ai_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("model_used", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_follower_ai_insights_channel_id",
        "follower_ai_insights",
        ["channel_id"],
    )


def downgrade() -> None:
    op.drop_table("follower_ai_insights")
