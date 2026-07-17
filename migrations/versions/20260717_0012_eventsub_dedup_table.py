"""eventsub dedup in postgres (drops the Valkey dependency in production)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-17

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eventsub_messages",
        sa.Column("message_id", sa.String(64), primary_key=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # The prune deletes by age on every claim; without this it is a seq scan.
    op.create_index(
        "ix_eventsub_messages_received_at", "eventsub_messages", ["received_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_eventsub_messages_received_at", table_name="eventsub_messages")
    op.drop_table("eventsub_messages")
