"""campaign recipients (cold-email attribution)

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-24

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None

# Grafana reads product metrics through a read-only user that was granted table
# by table, so a new table is invisible to the dashboards until it is granted
# too. Guarded because the role only exists on the managed cluster.
GRANT_GRAFANA_RO = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        GRANT SELECT ON campaign_recipients TO grafana_ro;
    END IF;
END $$;
"""


def upgrade() -> None:
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
    op.execute(GRANT_GRAFANA_RO)


def downgrade() -> None:
    op.drop_table("campaign_recipients")
