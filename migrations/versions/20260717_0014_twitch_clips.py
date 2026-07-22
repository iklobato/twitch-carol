"""twitch clips

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-17

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "twitch_clips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey("streams.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("clip_id", sa.String(128), nullable=False, unique=True),
        sa.Column("edit_url", sa.String(512), nullable=False),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.Column("title", sa.String(140), nullable=True),
        sa.Column("kept", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("twitch_clips")
