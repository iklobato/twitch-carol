"""Campaign funnel per batch: /howto?ref= visit -> Connect click -> sign-up.

The cold email links to /howto?ref=<batch>; nothing else identifies the reader,
so these are the only three numbers a batch has besides replies."""

from unittest.mock import Mock

import pytest
from sqlalchemy import select

from apps.api import auth
from core.campaign import REF_COOKIE
from core.channels import upsert_channel
from core.models import CampaignClick, CampaignStep, Channel
from core.twitch import TokenGrant, TwitchUser
from tests.factories import make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

GRANT = TokenGrant(
    access_token="access-1", refresh_token="refresh-1", expires_in=14400, scope=[]
)
USER = TwitchUser(id="777", login="novo", display_name="Novo")


def _steps(db) -> list[tuple[str, CampaignStep]]:
    return [(c.ref, c.step) for c in db.scalars(select(CampaignClick))]


def test_howto_with_a_batch_ref_counts_the_visit_and_keeps_the_batch(
    api_client, db
) -> None:
    resp = api_client.get("/howto?ref=lote-en-20", headers={"Accept-Language": "en"})

    assert resp.status_code == 200
    assert _steps(db) == [("lote-en-20", CampaignStep.HOWTO)]
    assert f"{REF_COOKIE}=lote-en-20" in resp.headers.get("set-cookie", "")


@pytest.mark.parametrize("ref", ["", "x", "lote-", "LOTE-1", "lote-1;drop", "a" * 40])
def test_howto_ignores_a_ref_that_is_not_a_batch_name(api_client, db, ref) -> None:
    resp = api_client.get("/howto", params={"ref": ref})

    assert resp.status_code == 200
    assert _steps(db) == []
    assert REF_COOKIE not in resp.headers.get("set-cookie", "")


def test_howto_still_serves_the_page_when_counting_fails(
    api_client, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    def broken_commit() -> None:
        raise OperationalError("insert", {}, Exception("db down"))

    monkeypatch.setattr(db, "commit", broken_commit)

    resp = api_client.get("/howto?ref=lote-23", headers={"Accept-Language": "en"})

    assert resp.status_code == 200
    assert "How it works" in resp.text


def test_connect_click_is_counted_for_the_batch_in_the_cookie(api_client, db) -> None:
    api_client.cookies.set(REF_COOKIE, "lote-23")

    resp = api_client.get("/auth/login", follow_redirects=False)

    assert resp.status_code == 307
    assert _steps(db) == [("lote-23", CampaignStep.LOGIN)]


def test_connect_without_a_campaign_cookie_counts_nothing(api_client, db) -> None:
    resp = api_client.get("/auth/login", follow_redirects=False)

    assert resp.status_code == 307
    assert _steps(db) == []


def test_callback_stamps_the_batch_on_a_new_channel_and_spends_the_cookie(
    api_client, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "exchange_code", lambda code: GRANT)
    monkeypatch.setattr(auth, "get_user", lambda token: USER)
    monkeypatch.setattr(auth, "_backfill_best_effort", lambda db, channel: None)
    monkeypatch.setattr(auth, "_sync_eventsub_best_effort", lambda channel: None)
    api_client.cookies.set("oauth_state", "s")
    api_client.cookies.set(REF_COOKIE, "lote-en-20")

    resp = api_client.get(
        "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )

    assert resp.status_code == 307
    channel = db.scalar(select(Channel).where(Channel.login == "novo"))
    assert channel is not None and channel.signup_ref == "lote-en-20"
    assert f'{REF_COOKIE}=""' in resp.headers.get("set-cookie", "")


def test_new_channel_gets_the_signup_ref() -> None:
    db = Mock()
    db.scalar.return_value = None

    channel = upsert_channel(db, USER, GRANT, signup_ref="lote-23")

    assert channel.signup_ref == "lote-23"


def test_existing_channel_is_not_credited_to_the_campaign(db) -> None:
    """Someone who already uses the product and clicks a campaign link was not
    brought in by it."""
    existing = make_channel(db)
    db.commit()
    user = TwitchUser(
        id=str(existing.twitch_user_id), login=existing.login, display_name="X"
    )

    channel = upsert_channel(db, user, GRANT, signup_ref="lote-23")

    assert channel.id == existing.id
    assert channel.signup_ref is None
