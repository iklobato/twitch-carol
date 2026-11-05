"""campaign_clicks + channels.signup_ref: campaign funnel per batch

The cold email links to /howto?ref=<batch>. The API records the visit and the
click on Connect in campaign_clicks, and the batch lands on the new channel as
signup_ref, so each batch reads as visits -> login clicks -> sign-ups. Only the
batch name is stored.

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("signup_ref", sa.String(32), nullable=True))
    step = sa.Enum("howto", "login", name="campaign_step", native_enum=False)
    op.create_table(
        "campaign_clicks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ref", sa.String(32), nullable=False),
        sa.Column("step", step, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_campaign_clicks_ref", "campaign_clicks", ["ref"])


def downgrade() -> None:
    op.drop_index("ix_campaign_clicks_ref", table_name="campaign_clicks")
    op.drop_table("campaign_clicks")
    op.drop_column("channels", "signup_ref")
