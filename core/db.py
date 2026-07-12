from datetime import date
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    if first.month == 12:
        return first, date(first.year + 1, 1, 1)
    return first, date(first.year, first.month + 1, 1)


def chat_partition_ddl(day: date) -> str:
    first, next_first = month_bounds(day)
    name = f"chat_messages_y{first.year}m{first.month:02d}"
    return (
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF chat_messages "
        f"FOR VALUES FROM ('{first.isoformat()}') TO ('{next_first.isoformat()}')"
    )


def ensure_chat_partition(session: Session, day: date) -> None:
    """Create the monthly chat partition if missing. Called before inserting chat."""
    session.execute(text(chat_partition_ddl(day)))
