"""goal created_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: existing goal snapshots predate this and only gain a value on
    # the next connect, when the backfill re-reads Helix (which returns it).
    op.add_column(
        "goals", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("goals", "created_at")
