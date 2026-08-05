from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from core.channels import channel_language, ensure_fresh_token, upsert_channel
from core.crypto import decrypt_secret, encrypt_secret
from core.models import Channel
from core.twitch import TokenGrant, TwitchAuthError, TwitchUser

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

GRANT = TokenGrant(
    access_token="access-1",
    refresh_token="refresh-1",
    expires_in=14400,
    scope=["bits:read"],
)
USER = TwitchUser(id="123", login="henry", display_name="Henry")


def _decrypted(value: bytes | None) -> str:
    assert value is not None
    return decrypt_secret(value)


def _expires_at(channel: Channel) -> datetime:
    assert channel.token_expires_at is not None
    return channel.token_expires_at


def _channel_with_tokens(expires_at: datetime) -> Channel:
    return Channel(
        twitch_user_id=123,
        login="henry",
        display_name="Henry",
        access_token_encrypted=encrypt_secret("access-1"),
        refresh_token_encrypted=encrypt_secret("refresh-1"),
        token_expires_at=expires_at,
    )


def test_upsert_creates_channel_with_encrypted_tokens() -> None:
    db = Mock()
    db.scalar.return_value = None

    channel = upsert_channel(db, USER, GRANT)

    db.add.assert_called_once_with(channel)
    db.flush.assert_called_once()
    assert channel.twitch_user_id == 123
    assert channel.access_token_encrypted != b"access-1"
    assert _decrypted(channel.access_token_encrypted) == "access-1"
    assert _decrypted(channel.refresh_token_encrypted) == "refresh-1"
    assert channel.scopes == ["bits:read"]
    assert _expires_at(channel) > datetime.now(UTC)


def test_upsert_updates_existing_channel() -> None:
    existing = _channel_with_tokens(datetime.now(UTC))
    db = Mock()
    db.scalar.return_value = existing

    new_grant = TokenGrant(
        access_token="access-2", refresh_token="refresh-2", expires_in=14400, scope=[]
    )
    channel = upsert_channel(
        db, TwitchUser(id="123", login="henry2", display_name="H2"), new_grant
    )

    db.add.assert_not_called()
    assert channel is existing
    assert channel.login == "henry2"
    assert _decrypted(channel.access_token_encrypted) == "access-2"


def test_ensure_fresh_token_skips_refresh_when_valid() -> None:
    channel = _channel_with_tokens(datetime.now(UTC) + timedelta(hours=2))
    db = Mock()

    token = ensure_fresh_token(db, channel)

    assert token == "access-1"
    db.flush.assert_not_called()


def test_ensure_fresh_token_refreshes_when_expired() -> None:
    channel = _channel_with_tokens(datetime.now(UTC) - timedelta(minutes=1))
    db = Mock()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "access-2",
                "refresh_token": "refresh-2",
                "expires_in": 14400,
                "scope": ["bits:read"],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = ensure_fresh_token(db, channel, client=client)

    assert token == "access-2"
    assert "grant_type=refresh_token" in seen["body"]
    assert "refresh-1" in seen["body"]
    # rotated tokens persisted encrypted
    assert _decrypted(channel.access_token_encrypted) == "access-2"
    assert _decrypted(channel.refresh_token_encrypted) == "refresh-2"
    assert _expires_at(channel) > datetime.now(UTC)
    db.flush.assert_called_once()


def test_ensure_fresh_token_without_refresh_token_raises() -> None:
    channel = Channel(twitch_user_id=123, login="henry", display_name="Henry")
    with pytest.raises(TwitchAuthError, match="no refresh token"):
        ensure_fresh_token(Mock(), channel)


def test_upsert_grava_o_idioma_do_canal(db) -> None:
    """O idioma decide o lexico da analise de chat, o idioma dos insights e o da
    tela. Sem ele, streamer de fora do Brasil recebe 'the' e 'you' como assuntos
    da live."""
    channel = upsert_channel(db, USER, GRANT, "en")

    assert channel.language == "en"


def test_upsert_mantem_portugues_quando_a_helix_nao_diz_o_idioma(db) -> None:
    channel = upsert_channel(db, USER, GRANT, None)

    assert channel.language == "pt"


def test_upsert_keeps_the_language_captured_at_sign_up(db) -> None:
    """broadcaster_language is a setting the streamer can flip on Twitch at any
    time. Following it on every login would move a live Portuguese channel to
    English mid-use and hand Whisper the wrong language for its audio, so the
    value is captured once and left alone."""
    upsert_channel(db, USER, GRANT, "pt")

    channel = upsert_channel(db, USER, GRANT, "en")

    assert channel.language == "pt"


def test_idioma_cai_no_padrao_quando_a_helix_falha() -> None:
    """Login nao pode quebrar porque a Helix esta fora: idioma vazio quebraria a
    escolha de lexico depois."""

    def helix_fora(_ids, _client=None):
        raise TwitchAuthError("Twitch /channels returned 500")

    assert channel_language(123, buscar=helix_fora) == "pt"
