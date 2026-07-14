from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSessionType

from core.config import get_settings
from core.crypto import SESSION_MAX_AGE_SECONDS, Session, read_session_token
from core.db import session_factory
from core.models import Channel

SESSION_COOKIE = "session"


def get_db() -> Iterator[DbSessionType]:
    with session_factory()() as session:
        yield session


DbSession = Annotated[DbSessionType, Depends(get_db)]


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=get_settings().public_base_url.startswith("https://"),
    )


def current_session(request: Request) -> Session:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = read_session_token(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session


CurrentSession = Annotated[Session, Depends(current_session)]


def current_channel(session: CurrentSession, db: DbSession) -> Channel:
    channel = db.get(Channel, session.channel_id)
    if channel is None:
        raise HTTPException(status_code=401, detail="Unknown channel")
    return channel


CurrentChannel = Annotated[Channel, Depends(current_channel)]
