from fastapi import FastAPI
from pydantic import BaseModel

from apps.api.actionable import router as actionable_router
from apps.api.auth import router as auth_router
from apps.api.channel import router as channel_router
from apps.api.community import router as community_router
from apps.api.dashboard import router as dashboard_router
from apps.api.deps import CurrentChannel
from apps.api.eventsub import router as eventsub_router
from apps.api.finance import router as finance_router
from core.logging_setup import setup_logging

setup_logging()

app = FastAPI(title="Stream Intel API")
app.include_router(auth_router)
app.include_router(eventsub_router)
app.include_router(dashboard_router)
app.include_router(community_router)
app.include_router(channel_router)
app.include_router(actionable_router)
app.include_router(finance_router)


class MeResponse(BaseModel):
    twitch_user_id: int
    login: str
    display_name: str
    scopes: list[str]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
def me(channel: CurrentChannel) -> MeResponse:
    return MeResponse(
        twitch_user_id=channel.twitch_user_id,
        login=channel.login,
        display_name=channel.display_name,
        scopes=channel.scopes,
    )
