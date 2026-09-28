from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from apps.api import auth
from apps.api.main import app
from core.models import Subscription, Vip
from tests.factories import make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, follow_redirects=False)


def test_login_redirects_to_twitch_with_state_cookie(client: TestClient) -> None:
    response = client.get("/auth/login")
    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    assert location.hostname == "id.twitch.tv"
    state = parse_qs(location.query)["state"][0]
    assert response.cookies["oauth_state"] == state


def test_callback_rejects_mismatched_state(client: TestClient) -> None:
    client.cookies.set("oauth_state", "expected-state")
    response = client.get(
        "/auth/callback", params={"code": "abc", "state": "wrong-state"}
    )
    assert response.status_code == 400


def test_callback_rejects_missing_state_cookie(client: TestClient) -> None:
    response = client.get(
        "/auth/callback", params={"code": "abc", "state": "some-state"}
    )
    assert response.status_code == 400


def test_callback_surfaces_twitch_error(client: TestClient) -> None:
    response = client.get("/auth/callback", params={"error": "access_denied"})
    assert response.status_code == 400


def test_me_requires_session(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401


def test_me_rejects_invalid_session_cookie(client: TestClient) -> None:
    client.cookies.set("session", "garbage")
    response = client.get("/api/me")
    assert response.status_code == 401


def test_logout_clears_session(client: TestClient) -> None:
    client.cookies.set("session", "anything")
    response = client.get("/auth/logout")
    assert response.status_code == 307
    set_cookie = response.headers["set-cookie"]
    assert 'session=""' in set_cookie


def test_backfill_database_error_does_not_block_the_other_steps(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = make_channel(db)
    db.commit()

    def duplicate_subscribers(db, channel) -> int:
        for _ in range(2):
            db.add(Subscription(channel_id=channel.id, twitch_user_id=1, login="a"))
        return 2

    def one_vip(db, channel) -> int:
        db.add(Vip(channel_id=channel.id, twitch_user_id=2, login="vip"))
        return 1

    monkeypatch.setattr(
        auth,
        "BACKFILL_STEPS",
        (("subs", duplicate_subscribers), ("vips", one_vip)),
    )

    auth._backfill_best_effort(db, channel)

    vips = db.query(Vip.login).filter_by(channel_id=channel.id).all()
    assert [login for (login,) in vips] == ["vip"]
    assert db.query(Subscription).filter_by(channel_id=channel.id).count() == 0
    assert channel.followers_synced_at is None
