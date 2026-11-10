"""unique chat message id and one viewer sample per minute

A standby capture worker now runs next to the official one, so both read the
same IRC channel and the same Helix numbers. These indexes make the second copy
of every write a no-op (the collectors use ON CONFLICT DO NOTHING).

chat_messages is partitioned by month (400 MB in production on 2026-11-10), so
the unique index is built partition by partition with CREATE INDEX
CONCURRENTLY and attached to an index created ON ONLY the parent: no partition
is ever locked against inserts while a live is being captured.

Before the index can exist, the 7 duplicate chat rows left by the 2026-07-16
double capture (streams 39-44, measured 2026-11-10) are removed. In each group
the row whose stream covers the message time is kept, then the lowest id. The
downgrade drops the indexes; it does not bring those duplicates back.

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | None = None
depends_on: str | None = None

CHAT_INDEX = "uq_chat_messages_message_sent"
VIEWER_INDEX = "uq_viewer_samples_stream_sampled"
OLD_VIEWER_INDEX = "ix_viewer_samples_stream_sampled"

DELETE_CHAT_DUPLICATES = """
WITH duplicate_keys AS (
    SELECT message_id, sent_at
    FROM chat_messages
    WHERE message_id IS NOT NULL
    GROUP BY message_id, sent_at
    HAVING count(*) > 1
),
ranked AS (
    SELECT m.id, m.sent_at,
           row_number() OVER (
               PARTITION BY m.message_id, m.sent_at
               ORDER BY (m.sent_at >= s.started_at
                         AND (s.ended_at IS NULL OR m.sent_at <= s.ended_at)) DESC,
                        m.id
           ) AS position
    FROM chat_messages m
    JOIN duplicate_keys d ON d.message_id = m.message_id AND d.sent_at = m.sent_at
    JOIN streams s ON s.id = m.stream_id
)
DELETE FROM chat_messages c
USING ranked r
WHERE c.id = r.id AND c.sent_at = r.sent_at AND r.position > 1
"""

CHAT_PARTITIONS = """
SELECT child.relname
FROM pg_inherits
JOIN pg_class child ON child.oid = pg_inherits.inhrelid
WHERE pg_inherits.inhparent = 'chat_messages'::regclass
ORDER BY child.relname
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(DELETE_CHAT_DUPLICATES))
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {CHAT_INDEX} "
        "ON ONLY chat_messages (message_id, sent_at)"
    )
    partitions = [row[0] for row in bind.execute(sa.text(CHAT_PARTITIONS))]
    quote = bind.dialect.identifier_preparer.quote
    with op.get_context().autocommit_block():
        for partition in partitions:
            child_index = quote(f"uq_{partition}_message_sent")
            op.execute(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {child_index} "
                f"ON {quote(partition)} (message_id, sent_at)"
            )
            op.execute(f"ALTER INDEX {CHAT_INDEX} ATTACH PARTITION {child_index}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {VIEWER_INDEX} "
            "ON viewer_samples (stream_id, sampled_at)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {OLD_VIEWER_INDEX}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {OLD_VIEWER_INDEX} "
            "ON viewer_samples (stream_id, sampled_at)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {VIEWER_INDEX}")
    # Dropping the parent index drops every attached partition index with it.
    op.execute(f"DROP INDEX IF EXISTS {CHAT_INDEX}")
