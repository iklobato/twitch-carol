"""streamer follower enrichment (collab fit)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "followers", sa.Column("stream_category", sa.String(128), nullable=True)
    )
    op.add_column(
        "followers", sa.Column("stream_language", sa.String(16), nullable=True)
    )
    op.add_column(
        "followers",
        sa.Column("streamer_enriched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("followers", "streamer_enriched_at")
    op.drop_column("followers", "stream_language")
    op.drop_column("followers", "stream_category")
