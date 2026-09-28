"""streams.category and followers.stream_category become text

A real Twitch game name is 139 characters, and both columns were
varchar(128). On followers it failed the same enrichment batch on every
pass; on streams it would fail the channel.update webhook the moment a live
channel switched to such a game. Twitch documents no maximum, so no length
is picked here. varchar -> text is binary compatible in Postgres: no table
rewrite.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | None = None
depends_on: str | None = None

COLUMNS = (("streams", "category"), ("followers", "stream_category"))


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(table, column, type_=sa.Text(), existing_type=sa.String(128))


def downgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(128),
            existing_type=sa.Text(),
            postgresql_using=f"left({column}, 128)",
        )
