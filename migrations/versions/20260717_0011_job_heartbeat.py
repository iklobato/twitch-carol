"""job heartbeat (orphan recovery when a worker dies mid-job)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True)
    )
    # The reclaim scans running jobs by heartbeat on every worker poll (5s).
    op.create_index(
        "ix_jobs_status_heartbeat", "jobs", ["type", "status", "last_heartbeat"]
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_heartbeat", table_name="jobs")
    op.drop_column("jobs", "last_heartbeat")
