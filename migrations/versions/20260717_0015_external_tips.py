"""external tips + streamelements connector

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-17

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("streamelements_account_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column("streamelements_jwt_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column(
            "streamelements_synced_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_table(
        "external_tips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("tipper", sa.String(128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("tipped_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.UniqueConstraint("source", "external_id", name="uq_external_tips_source_id"),
    )


def downgrade() -> None:
    op.drop_table("external_tips")
    op.drop_column("channels", "streamelements_synced_at")
    op.drop_column("channels", "streamelements_jwt_encrypted")
    op.drop_column("channels", "streamelements_account_id")
