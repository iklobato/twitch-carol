"""The onboarding gate: a channel declares what it speaks before anything reads
its chat, instead of the product inferring it and being confidently wrong."""

import pytest

from tests.conftest import login_as
from tests.factories import make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_me_reports_a_fresh_channel_as_needing_onboarding(api_client, db) -> None:
    channel = make_channel(db)
    db.commit()
    login_as(api_client, channel)

    assert api_client.get("/api/me").json()["needs_onboarding"] is True


def test_declaring_the_language_stores_it_and_closes_the_gate(api_client, db) -> None:
    channel = make_channel(db)
    db.commit()
    login_as(api_client, channel)

    response = api_client.patch(
        "/api/channel/preferences", json={"stream_language": "pt"}
    )

    assert response.status_code == 204
    db.refresh(channel)
    assert channel.spoken_language == "pt"
    assert channel.onboarded_at is not None
    assert api_client.get("/api/me").json()["needs_onboarding"] is False


def test_an_unsupported_language_is_refused(api_client, db) -> None:
    """Accepting "es" would store a language with no stopword list and no
    lexicon behind it, and the chat analysis would silently read it as
    Portuguese. Better to refuse than to pretend."""
    channel = make_channel(db)
    db.commit()
    login_as(api_client, channel)

    response = api_client.patch(
        "/api/channel/preferences", json={"stream_language": "es"}
    )

    assert response.status_code == 422
    db.refresh(channel)
    assert channel.spoken_language is None
    assert channel.onboarded_at is None


def test_onboarding_requires_a_session(api_client) -> None:
    assert (
        api_client.patch(
            "/api/channel/preferences", json={"stream_language": "pt"}
        ).status_code
        == 401
    )


def test_the_browser_timezone_replaces_the_utc_default(api_client, db) -> None:
    """Until this field is written, the best weekday and hour to go live, the
    per-day chatter counts and the monetization period are all computed in UTC,
    which is three hours off for a Brazilian channel and splits a night stream
    across two days."""
    channel = make_channel(db)
    db.commit()
    login_as(api_client, channel)

    response = api_client.patch(
        "/api/channel/preferences",
        json={"stream_language": "pt", "timezone": "America/Sao_Paulo"},
    )

    assert response.status_code == 204
    db.refresh(channel)
    assert channel.timezone == "America/Sao_Paulo"
    assert api_client.get("/api/me").json()["timezone"] == "America/Sao_Paulo"


def test_an_unknown_timezone_is_refused(api_client, db) -> None:
    channel = make_channel(db)
    db.commit()
    login_as(api_client, channel)

    response = api_client.patch(
        "/api/channel/preferences",
        json={"stream_language": "pt", "timezone": "Mars/Olympus"},
    )

    assert response.status_code == 422
    db.refresh(channel)
    assert channel.timezone == "UTC"
    assert channel.onboarded_at is None


def test_settings_can_change_a_language_already_chosen(api_client, db) -> None:
    """The gate asks once. Someone who picked wrong, or who changed what they
    stream in, needs a way back that is not a database update."""
    channel = make_channel(db)
    db.commit()
    login_as(api_client, channel)
    api_client.patch("/api/channel/preferences", json={"stream_language": "pt"})
    db.refresh(channel)
    first_answer = channel.onboarded_at

    api_client.patch(
        "/api/channel/preferences",
        json={"stream_language": "en", "screen_language": "pt"},
    )

    db.refresh(channel)
    assert channel.spoken_language == "en"
    assert channel.language == "pt"
    # the gate stays closed on the first answer, not reopened by an edit
    assert channel.onboarded_at == first_answer
