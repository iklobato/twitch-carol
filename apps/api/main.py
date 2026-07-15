from fastapi import FastAPI
from pydantic import BaseModel

from apps.api.actionable import router as actionable_router
from apps.api.admin import is_admin_login
from apps.api.admin import router as admin_router
from apps.api.auth import router as auth_router
from apps.api.channel import router as channel_router
from apps.api.community import router as community_router
from apps.api.dashboard import router as dashboard_router
from apps.api.deps import CurrentChannel, CurrentSession, DbSession
from apps.api.eventsub import router as eventsub_router
from apps.api.finance import router as finance_router
from apps.api.followers import router as followers_router
from core.logging_setup import setup_logging
from core.models import Channel

setup_logging()

app = FastAPI(title="Stream Intel API")
app.include_router(auth_router)
app.include_router(eventsub_router)
app.include_router(dashboard_router)
app.include_router(community_router)
app.include_router(channel_router)
app.include_router(actionable_router)
app.include_router(finance_router)
app.include_router(followers_router)
app.include_router(admin_router)


class Impersonation(BaseModel):
    as_login: str
    admin_login: str


class MeResponse(BaseModel):
    twitch_user_id: int
    login: str
    display_name: str
    scopes: list[str]
    is_admin: bool = False
    impersonating: Impersonation | None = None


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
def me(session: CurrentSession, channel: CurrentChannel, db: DbSession) -> MeResponse:
    impersonating = None
    if session.admin_id is not None:
        admin = db.get(Channel, session.admin_id)
        impersonating = Impersonation(
            as_login=channel.login,
            admin_login=admin.login if admin else str(session.admin_id),
        )
    is_admin = session.admin_id is None and is_admin_login(channel.login)
    return MeResponse(
        twitch_user_id=channel.twitch_user_id,
        login=channel.login,
        display_name=channel.display_name,
        scopes=channel.scopes,
        is_admin=is_admin,
        impersonating=impersonating,
    )
