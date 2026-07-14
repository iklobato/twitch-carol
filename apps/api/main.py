from fastapi import FastAPI
from pydantic import BaseModel

from apps.api.auth import router as auth_router
from apps.api.billing import router as billing_router
from apps.api.community import router as community_router
from apps.api.dashboard import router as dashboard_router
from apps.api.deps import CurrentChannel, DbSession
from apps.api.eventsub import router as eventsub_router
from core.logging_setup import setup_logging
from core.streams import channel_stream_count

setup_logging()

app = FastAPI(title="Stream Intel API")
app.include_router(auth_router)
app.include_router(eventsub_router)
app.include_router(dashboard_router)
app.include_router(community_router)
app.include_router(billing_router)


class MeResponse(BaseModel):
    twitch_user_id: int
    login: str
    display_name: str
    scopes: list[str]
    is_pro: bool
    trial_used: bool


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
def me(channel: CurrentChannel, db: DbSession) -> MeResponse:
    return MeResponse(
        twitch_user_id=channel.twitch_user_id,
        login=channel.login,
        display_name=channel.display_name,
        scopes=channel.scopes,
        is_pro=channel.is_pro,
        trial_used=channel_stream_count(db, channel.id) >= 1,
    )
