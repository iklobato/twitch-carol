"""Fernet-based encryption for OAuth tokens at rest and for the session cookie.

Uses the single FERNET_KEY from config for both. Tokens never appear in logs.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings

SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class Session:
    """Who the request acts as, and (when an admin is impersonating) who they
    really are. admin_id is None for a normal login."""

    channel_id: int
    admin_id: int | None = None


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


def create_session_token(channel_id: int, admin_id: int | None = None) -> str:
    payload: dict[str, int] = {"cid": channel_id}
    if admin_id is not None:
        payload["adm"] = admin_id
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def read_session_token(token: str) -> Session | None:
    """Returns the session, or None for an invalid/expired/tampered token."""
    try:
        raw = _fernet().decrypt(token.encode(), ttl=SESSION_MAX_AGE_SECONDS).decode()
    except InvalidToken:
        return None
    try:
        # Tokens minted before impersonation existed are a bare channel id.
        return Session(channel_id=int(raw))
    except ValueError:
        pass
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return Session(channel_id=payload["cid"], admin_id=payload.get("adm"))
