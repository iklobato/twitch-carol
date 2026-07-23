"""streamelements oauth tokens

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-18

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("streamelements_token_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column("streamelements_refresh_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column(
            "streamelements_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("channels", "streamelements_token_expires_at")
    op.drop_column("channels", "streamelements_refresh_encrypted")
    op.drop_column("channels", "streamelements_token_encrypted")
