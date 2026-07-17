import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core import crypto
from core.config import get_settings
from core.db import chat_partition_ddl
from core.models import Base

TEST_DB_NAME = "stream_intel_test"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", f"postgresql+psycopg://app:app@localhost:5433/{TEST_DB_NAME}"
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
    admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        connection = admin.connect()
    except OperationalError:  # docker stack down: DB-backed tests are skipped
        admin.dispose()
        pytest.skip("postgres (compose, localhost:5433) not available")

    # Postgres answered, so from here on a failure is a real problem and must be
    # loud. This used to be one blanket `except Exception -> skip`, which turned
    # "a leftover connection is blocking the DROP" into a green run with silent
    # skips: the suite reported success while whole files never ran.
    with connection:
        # A session left behind by a killed run holds the database and makes DROP
        # fail. It is never a session worth keeping.
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": TEST_DB_NAME},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
        connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

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

    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # https base_url so secure session/oauth cookies round-trip (production
    # sets them secure when PUBLIC_BASE_URL is https)
    yield TestClient(app, base_url="https://testserver")
    app.dependency_overrides.clear()


def login_as(client, channel) -> None:
    """Sets a valid session cookie for the given channel on the test client."""
    from core.crypto import create_session_token

    client.cookies.set("session", create_session_token(channel.id))
