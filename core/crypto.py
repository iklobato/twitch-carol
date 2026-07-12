"""Fernet-based encryption for OAuth tokens at rest and for the session cookie.

Uses the single FERNET_KEY from config for both. Tokens never appear in logs.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings

SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise RuntimeError("FERNET_KEY is not set")
    return Fernet(key)


def encrypt_secret(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt_secret(value: bytes) -> str:
    return _fernet().decrypt(value).decode()


def create_session_token(channel_id: int) -> str:
    return _fernet().encrypt(str(channel_id).encode()).decode()


def read_session_token(token: str) -> int | None:
    """Returns the channel id, or None for an invalid/expired/tampered token."""
    try:
        return int(_fernet().decrypt(token.encode(), ttl=SESSION_MAX_AGE_SECONDS))
    except (InvalidToken, ValueError):
        return None
