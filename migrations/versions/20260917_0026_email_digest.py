"""channel email + digest opt-out flags, email_digest_log

Revision ID: 0026
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0024"
branch_labels: str | None = None
depends_on: str | None = None

DIGEST_PERIOD = "digest_period"


def upgrade() -> None:
    op.add_column("channels", sa.Column("email", sa.String(256), nullable=True))
    op.add_column(
        "channels",
        sa.Column(
            "digest_weekly", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "channels",
        sa.Column(
            "digest_monthly", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )

    period = sa.Enum("weekly", "monthly", name=DIGEST_PERIOD, native_enum=False)
    op.create_table(
        "email_digest_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
        ),
        sa.Column("period", period, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reserved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(128), nullable=True),
        sa.UniqueConstraint(
            "channel_id", "period", "period_start", name="uq_email_digest_log_window"
        ),
    )
    op.create_index(
        "ix_email_digest_log_channel_id", "email_digest_log", ["channel_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_email_digest_log_channel_id", table_name="email_digest_log")
    op.drop_table("email_digest_log")
    op.drop_column("channels", "digest_monthly")
    op.drop_column("channels", "digest_weekly")
    op.drop_column("channels", "email")
