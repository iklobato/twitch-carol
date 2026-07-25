"""drop campaign recipients (email attribution dropped)

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-24

0018 already ran in production, so it stays in the history and this reverses it
instead: deleting that file would leave the live database pointing at a revision
alembic can no longer find.

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("campaign_recipients")


def downgrade() -> None:
    op.create_table(
        "campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(16), nullable=False, unique=True),
        sa.Column("batch", sa.String(16), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
