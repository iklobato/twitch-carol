"""follower enrichment and recommendations

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enrichment columns are nullable: existing followers gain them on the next
    # connect, when the backfill reads Helix Get Users.
    op.add_column("followers", sa.Column("display_name", sa.String(128), nullable=True))
    op.add_column(
        "followers", sa.Column("profile_image_url", sa.String(256), nullable=True)
    )
    op.add_column("followers", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "followers", sa.Column("broadcaster_type", sa.String(16), nullable=True)
    )
    op.add_column(
        "followers",
        sa.Column("account_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "followers",
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "follower_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("model_used", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_follower_recommendations_channel_id",
        "follower_recommendations",
        ["channel_id"],
    )


def downgrade() -> None:
    op.drop_table("follower_recommendations")
    for column in (
        "enriched_at",
        "account_created_at",
        "broadcaster_type",
        "description",
        "profile_image_url",
        "display_name",
    ):
        op.drop_column("followers", column)
