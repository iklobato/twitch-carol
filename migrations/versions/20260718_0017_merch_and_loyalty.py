"""external tip kind + streamelements loyalty snapshot

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-18

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_tips",
        sa.Column(
            "kind", sa.String(16), nullable=False, server_default="tip"
        ),  # tip | merch
    )
    op.create_table(
        "se_loyalty",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "channel_id", "username", name="uq_se_loyalty_channel_user"
        ),
    )


def downgrade() -> None:
    op.drop_table("se_loyalty")
    op.drop_column("external_tips", "kind")
