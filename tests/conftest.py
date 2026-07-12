import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from core import crypto
from core.config import get_settings
from core.db import chat_partition_ddl
from core.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5433/stream_intel_test"
)
ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5433/app"
)


def _clear_settings_caches() -> None:
    get_settings.cache_clear()
    crypto._fernet.cache_clear()


@pytest.fixture
def fernet_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    _clear_settings_caches()
    yield
    _clear_settings_caches()


@pytest.fixture
def twitch_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TWITCH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8080")
    _clear_settings_caches()
    yield
    _clear_settings_caches()


class FakeValkey:
    """In-memory stand-in for the two Valkey operations the app uses."""

    def __init__(self) -> None:
        self.sets: dict[str, str] = {}
        self.streams: dict[str, list[dict]] = {}

    def set(self, key, value, nx: bool = False, ex: int | None = None):
        if nx and key in self.sets:
            return None
        self.sets[key] = str(value)
        return True

    def xadd(self, stream_key, fields):
        self.streams.setdefault(stream_key, []).append(dict(fields))
        return f"{len(self.streams[stream_key])}-0"


@pytest.fixture
def fake_valkey() -> FakeValkey:
    return FakeValkey()


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    """Dedicated test database on the local compose Postgres. Schema from the
    model metadata plus chat partitions covering the test time window."""
    try:
        admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS stream_intel_test"))
            conn.execute(text("CREATE DATABASE stream_intel_test"))
        admin.dispose()
    except Exception:  # docker stack down: DB-backed tests are skipped
        pytest.skip("postgres (compose, localhost:5433) not available")

    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        now = datetime.now(UTC).date()
        for day in (now - timedelta(days=31), now, now + timedelta(days=31)):
            conn.execute(text(chat_partition_ddl(day)))
    yield engine
    engine.dispose()


@pytest.fixture
def db(pg_engine: Engine) -> Iterator[Session]:
    """Per-test session inside an outer transaction: commits become
    savepoints and everything rolls back at teardown."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def api_client(
    db: Session, fernet_key: None, twitch_env: None, fake_valkey: FakeValkey
):
    from fastapi.testclient import TestClient

    from apps.api.deps import get_db
    from apps.api.main import app
    from core.queues import get_valkey

    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_valkey] = lambda: fake_valkey
    yield TestClient(app)
    app.dependency_overrides.clear()


def login_as(client, channel) -> None:
    """Sets a valid session cookie for the given channel on the test client."""
    from core.crypto import create_session_token

    client.cookies.set("session", create_session_token(channel.id))
