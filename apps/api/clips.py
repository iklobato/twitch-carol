"""Live auto-clips created on Twitch at best moments; the streamer curates them
(keep/hide, title). Deleting a clip isn't a Twitch API operation, so hiding is a
local flag."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.deps import CurrentChannel, DbSession
from core.models import TwitchClip

router = APIRouter(prefix="/api")


class ClipOut(BaseModel):
    id: int
    clip_id: str
    edit_url: str
    reason: str | None
    title: str | None
    kept: bool
    created_at: datetime


class ClipCuration(BaseModel):
    kept: bool | None = None
    title: str | None = None


def _out(clip: TwitchClip) -> ClipOut:
    return ClipOut(
        id=clip.id,
        clip_id=clip.clip_id,
        edit_url=clip.edit_url,
        reason=clip.reason,
        title=clip.title,
        kept=clip.kept,
        created_at=clip.created_at,
    )


@router.get("/clips")
def list_clips(channel: CurrentChannel, db: DbSession) -> list[ClipOut]:
    rows = db.scalars(
        select(TwitchClip)
        .where(TwitchClip.channel_id == channel.id)
        .order_by(TwitchClip.created_at.desc())
    ).all()
    return [_out(clip) for clip in rows]


@router.patch("/clips/{clip_row_id}")
def curate_clip(
    clip_row_id: int,
    body: ClipCuration,
    channel: CurrentChannel,
    db: DbSession,
) -> ClipOut:
    clip = db.get(TwitchClip, clip_row_id)
    if clip is None or clip.channel_id != channel.id:
        raise HTTPException(status_code=404, detail="clip not found")
    if body.kept is not None:
        clip.kept = body.kept
    if body.title is not None:
        clip.title = body.title
    db.commit()
    return _out(clip)
