"""Public unsubscribe link: token validation and the flags it clears."""

import pytest

from core.crypto import create_unsubscribe_token
from tests.factories import make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_unsubscribe_clears_both_flags_by_default(api_client, db) -> None:
    channel = make_channel(db)
    token = create_unsubscribe_token(channel.id)

    response = api_client.get("/api/digest/unsubscribe", params={"t": token})

    assert response.status_code == 200
    db.refresh(channel)
    assert channel.digest_weekly is False
    assert channel.digest_monthly is False


def test_unsubscribe_can_target_a_single_period(api_client, db) -> None:
    channel = make_channel(db)
    token = create_unsubscribe_token(channel.id)

    response = api_client.get(
        "/api/digest/unsubscribe", params={"t": token, "period": "weekly"}
    )

    assert response.status_code == 200
    db.refresh(channel)
    assert channel.digest_weekly is False
    assert channel.digest_monthly is True


def test_unsubscribe_rejects_an_invalid_token(api_client, db) -> None:
    response = api_client.get("/api/digest/unsubscribe", params={"t": "garbage"})

    assert response.status_code == 400


def test_unsubscribe_rejects_an_unknown_period(api_client, db) -> None:
    channel = make_channel(db)
    token = create_unsubscribe_token(channel.id)

    response = api_client.get(
        "/api/digest/unsubscribe", params={"t": token, "period": "daily"}
    )

    assert response.status_code == 422
    db.refresh(channel)
    assert channel.digest_weekly is True


def test_unsubscribe_rejects_a_token_for_a_deleted_channel(api_client, db) -> None:
    token = create_unsubscribe_token(999_999)

    response = api_client.get("/api/digest/unsubscribe", params={"t": token})

    assert response.status_code == 404
