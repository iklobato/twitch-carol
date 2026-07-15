"""clips

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=False
        ),
        sa.Column("peak_id", sa.Integer(), sa.ForeignKey("peaks.id"), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_clips_stream_id", "clips", ["stream_id"])
    op.create_index(
        "uq_clips_stream_peak", "clips", ["stream_id", "peak_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("clips")
