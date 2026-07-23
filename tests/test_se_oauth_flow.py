"""StreamElements OAuth: the connect callback and OAuth-aware tips sync."""

from sqlalchemy.orm import Session

import apps.api.integrations as integrations_module
import core.integrations.tips as tips_module
from core.crypto import decrypt_secret
from core.integrations.streamelements import SEToken
from core.integrations.tips import set_streamelements_oauth, sync_streamelements_tips
from tests.conftest import login_as
from tests.factories import make_channel

CALLBACK = "/api/integrations/streamelements/callback"


def test_callback_stores_oauth_tokens(api_client, db: Session, monkeypatch) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    monkeypatch.setattr(
        integrations_module,
        "exchange_code",
        lambda code: SEToken(access_token="at", refresh_token="rt", expires_in=3600),
    )
    monkeypatch.setattr(integrations_module, "fetch_channel_id", lambda token: "chan-1")
    monkeypatch.setattr(
        integrations_module, "sync_streamelements_tips", lambda db, channel: 0
    )
    api_client.cookies.set("se_oauth_state", "st8")

    resp = api_client.get(f"{CALLBACK}?code=c&state=st8", follow_redirects=False)

    assert resp.status_code == 307  # redirect back into the app
    db.refresh(channel)
    assert channel.streamelements_account_id == "chan-1"
    assert channel.streamelements_token_encrypted is not None
    assert decrypt_secret(channel.streamelements_token_encrypted) == "at"


def test_callback_rejects_mismatched_state(api_client, db: Session) -> None:
    channel = make_channel(db, login="badstate")
    login_as(api_client, channel)
    api_client.cookies.set("se_oauth_state", "right")

    resp = api_client.get(f"{CALLBACK}?code=c&state=wrong", follow_redirects=False)

    assert resp.status_code == 400


def test_sync_prefers_oauth_token_over_jwt(db: Session, monkeypatch) -> None:
    channel = make_channel(db, login="oauthch")
    set_streamelements_oauth(
        db,
        channel,
        "acct",
        SEToken(access_token="at", refresh_token="rt", expires_in=3600),
    )
    captured: dict[str, object] = {}

    def fake_fetch(account_id, token, after=None):
        captured["token"] = token
        return []

    monkeypatch.setattr(tips_module, "fetch_tips", fake_fetch)
    sync_streamelements_tips(db, channel)

    assert captured["token"] == "at"


def test_sync_refreshes_expired_token(db: Session, monkeypatch) -> None:
    channel = make_channel(db, login="expch")
    set_streamelements_oauth(
        db,
        channel,
        "acct",
        SEToken(access_token="old", refresh_token="rt", expires_in=-10),  # expired
    )
    monkeypatch.setattr(
        tips_module,
        "refresh_access_token",
        lambda refresh: SEToken(
            access_token="new", refresh_token="rt2", expires_in=3600
        ),
    )
    captured: dict[str, object] = {}

    def fake_fetch(account_id, token, after=None):
        captured["token"] = token
        return []

    monkeypatch.setattr(tips_module, "fetch_tips", fake_fetch)
    sync_streamelements_tips(db, channel)

    assert captured["token"] == "new"  # used the refreshed token
    db.refresh(channel)
    assert decrypt_secret(channel.streamelements_token_encrypted) == "new"  # persisted
