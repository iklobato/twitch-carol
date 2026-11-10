"""at most one open (capturing, not ended) stream per channel

Each capture worker now asks Helix once a minute which channels are live and
opens the stream row when the stream.online webhook never arrived. The webhook
and the checks of both capture workers can open the same live at the same
moment; this partial unique index lets exactly one insert win
(start_stream uses ON CONFLICT DO NOTHING on it).

Production had at most one open stream per channel on 2026-11-10, so the index
builds without conflict. Built CONCURRENTLY: streams is written by the API on
every stream.online.

Revision ID: 0030
Revises: 0029
"""

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | None = None
depends_on: str | None = None

INDEX = "uq_streams_one_open_per_channel"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON streams (channel_id) "
            "WHERE status = 'capturing' AND ended_at IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
