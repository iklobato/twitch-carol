import pytest

from core.crypto import (
    create_session_token,
    decrypt_secret,
    encrypt_secret,
    read_session_token,
)

pytestmark = pytest.mark.usefixtures("fernet_key")


def test_secret_round_trip() -> None:
    encrypted = encrypt_secret("oauth-access-token")
    assert encrypted != b"oauth-access-token"
    assert decrypt_secret(encrypted) == "oauth-access-token"


def test_session_token_round_trip() -> None:
    token = create_session_token(42)
    assert read_session_token(token) == 42


def test_tampered_session_token_is_rejected() -> None:
    token = create_session_token(42)
    assert read_session_token(token[:-4] + "AAAA") is None


def test_garbage_session_token_is_rejected() -> None:
    assert read_session_token("not-a-fernet-token") is None
