"""Cold-email attribution: the ?e=<token> link on /howto identifies which
emailed streamer opened the page, and the Twitch connect that follows ties that
person to the channel they created."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import apps.api.auth as auth_module
from core.models import CampaignRecipient
from core.twitch import TokenGrant, TwitchUser

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

TOKEN = "aBc123xyz"


def make_recipient(db: Session, token: str = TOKEN, batch: str = "lote-2"):
    recipient = CampaignRecipient(token=token, batch=batch)
    db.add(recipient)
    db.flush()
    return recipient


def connect_twitch(api_client, db: Session, monkeypatch, login: str):
    """Drives the real OAuth callback with Twitch itself stubbed out."""
    monkeypatch.setattr(
        auth_module,
        "exchange_code",
        lambda code: TokenGrant(
            access_token="at", refresh_token="rt", expires_in=3600, scope=["bits:read"]
        ),
    )
    monkeypatch.setattr(
        auth_module,
        "get_user",
        lambda token: TwitchUser(id="99001", login=login, display_name=login),
    )
    monkeypatch.setattr(auth_module, "_backfill_best_effort", lambda db, channel: None)
    monkeypatch.setattr(auth_module, "_sync_eventsub_best_effort", lambda channel: None)
    api_client.cookies.set("oauth_state", "st8")
    return api_client.get(
        "/auth/callback", params={"code": "c", "state": "st8"}, follow_redirects=False
    )


def test_known_token_counts_the_visit_and_remembers_it(api_client, db: Session) -> None:
    recipient = make_recipient(db)

    resp = api_client.get(f"/howto?e={TOKEN}")

    assert resp.status_code == 200
    assert f"si_src={TOKEN}" in resp.headers.get("set-cookie", "")
    db.refresh(recipient)
    assert recipient.visit_count == 1
    assert recipient.visited_at is not None


def test_second_visit_counts_but_keeps_the_first_timestamp(api_client, db: Session) -> None:
    recipient = make_recipient(db, token="secondvisit")

    api_client.get("/howto?e=secondvisit")
    db.refresh(recipient)
    first_seen = recipient.visited_at

    api_client.get("/howto?e=secondvisit")
    db.refresh(recipient)

    assert recipient.visit_count == 2
    assert recipient.visited_at == first_seen


def test_unknown_token_is_ignored(api_client, db: Session) -> None:
    resp = api_client.get("/howto?e=notaknowntoken")

    assert resp.status_code == 200
    assert "si_src" not in resp.headers.get("set-cookie", "")
    assert db.scalars(select(CampaignRecipient)).all() == []


def test_malformed_token_never_reaches_the_database(api_client, db: Session) -> None:
    make_recipient(db, token="realtoken1")

    resp = api_client.get("/howto?e=' OR 1=1 --")

    assert resp.status_code == 200
    assert "si_src" not in resp.headers.get("set-cookie", "")


def test_connect_after_visit_links_the_channel(api_client, db: Session, monkeypatch) -> None:
    recipient = make_recipient(db, token="convertme")
    api_client.get("/howto?e=convertme")

    resp = connect_twitch(api_client, db, monkeypatch, login="converted")

    assert resp.status_code == 307
    db.refresh(recipient)
    assert recipient.channel_id is not None


def test_connect_without_a_campaign_cookie_links_nothing(
    api_client, db: Session, monkeypatch
) -> None:
    recipient = make_recipient(db, token="untouched1")

    connect_twitch(api_client, db, monkeypatch, login="organic")

    db.refresh(recipient)
    assert recipient.channel_id is None


def test_recipient_already_linked_is_not_repointed(api_client, db: Session, monkeypatch) -> None:
    recipient = make_recipient(db, token="linkedonce")
    api_client.get("/howto?e=linkedonce")
    connect_twitch(api_client, db, monkeypatch, login="firstchannel")
    db.refresh(recipient)
    first_channel_id = recipient.channel_id

    connect_twitch(api_client, db, monkeypatch, login="secondchannel")
    db.refresh(recipient)

    assert recipient.channel_id == first_channel_id


def test_link_is_personalised_only_in_the_href() -> None:
    from scripts.send_campaign_batch import HOWTO_URL, personalise

    html = f'<a href="{HOWTO_URL}">{HOWTO_URL}</a>'

    result = personalise(html, "tok12345")

    assert f'href="{HOWTO_URL}?e=tok12345"' in result
    assert f">{HOWTO_URL}<" in result  # visible text stays clean


def test_every_recipient_gets_a_distinct_token() -> None:
    from apps.api.marketing import TOKEN_PATTERN
    from scripts.send_campaign_batch import build_messages

    messages = build_messages(["a@x.com", "b@x.com", "c@x.com"], "<a href='x'>x</a>")

    tokens = [m["token"] for m in messages]
    assert len(set(tokens)) == 3
    assert all(TOKEN_PATTERN.match(token) for token in tokens)
