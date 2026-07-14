import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from apps.api.deps import CurrentChannel, CurrentSession, DbSession, set_session_cookie
from core.config import get_settings
from core.crypto import create_session_token
from core.models import Channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")


def _admin_logins() -> set[str]:
    raw = get_settings().admin_logins
    return {login.strip().lower() for login in raw.split(",") if login.strip()}


def is_admin_login(login: str) -> bool:
    return login.lower() in _admin_logins()


def require_admin(session: CurrentSession, channel: CurrentChannel) -> Channel:
    """The caller must be a real (non-impersonating) login on the allowlist."""
    if session.admin_id is not None:
        raise HTTPException(status_code=403, detail="Already impersonating")
    if not is_admin_login(channel.login):
        raise HTTPException(status_code=403, detail="Not an admin")
    return channel


AdminChannel = Annotated[Channel, Depends(require_admin)]


class ChannelOption(BaseModel):
    login: str
    display_name: str


@router.get("/channels")
def list_channels(admin: AdminChannel, db: DbSession) -> list[ChannelOption]:
    """Impersonation targets for the admin picker: every channel but the admin."""
    rows = (
        db.query(Channel).filter(Channel.id != admin.id).order_by(Channel.login).all()
    )
    return [ChannelOption(login=c.login, display_name=c.display_name) for c in rows]


# Registered before the /{login} route so "stop" is not read as a login.
@router.post("/impersonate/stop", status_code=204)
def stop_impersonation(session: CurrentSession, db: DbSession) -> Response:
    if session.admin_id is None:
        raise HTTPException(status_code=400, detail="Not impersonating")
    admin = db.get(Channel, session.admin_id)
    logger.info(
        "admin %s stopped impersonating channel %s",
        admin.login if admin else session.admin_id,
        session.channel_id,
    )
    response = Response(status_code=204)
    set_session_cookie(response, create_session_token(session.admin_id))
    return response


@router.post("/impersonate/{login}", status_code=204)
def start_impersonation(login: str, admin: AdminChannel, db: DbSession) -> Response:
    target = db.query(Channel).filter(Channel.login == login).one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"No channel {login!r}")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot impersonate yourself")
    logger.info(
        "admin %s impersonating %s",
        admin.login,
        target.login,
        extra={"admin_id": admin.id, "channel_id": target.id},
    )
    response = Response(status_code=204)
    set_session_cookie(response, create_session_token(target.id, admin_id=admin.id))
    return response
