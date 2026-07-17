"""stream records

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-17

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column(
            "stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=False
        ),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_stream_records_channel_metric",
        "stream_records",
        ["channel_id", "metric"],
    )
    op.create_index(
        "ix_stream_records_stream_id",
        "stream_records",
        ["stream_id"],
    )


def downgrade() -> None:
    op.drop_table("stream_records")
