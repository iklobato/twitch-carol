from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.crypto import read_session_token
from core.db import session_factory
from core.models import Channel

SESSION_COOKIE = "session"


def get_db() -> Iterator[Session]:
    with session_factory()() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def current_channel(request: Request, db: DbSession) -> Channel:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    channel_id = read_session_token(token)
    if channel_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=401, detail="Unknown channel")
    return channel


CurrentChannel = Annotated[Channel, Depends(current_channel)]
