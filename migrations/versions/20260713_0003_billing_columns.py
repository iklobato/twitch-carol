"""billing columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels", sa.Column("stripe_customer_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "channels", sa.Column("subscription_status", sa.String(32), nullable=True)
    )
    op.add_column(
        "channels",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_channels_stripe_customer_id", "channels", ["stripe_customer_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_channels_stripe_customer_id", table_name="channels")
    op.drop_column("channels", "current_period_end")
    op.drop_column("channels", "subscription_status")
    op.drop_column("channels", "stripe_customer_id")
