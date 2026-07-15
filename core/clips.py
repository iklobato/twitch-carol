"""Auto-clips: cut short videos from the stream's VOD around detected peaks and
store them. Runs post-analysis (best-effort), so it never touches live capture.

The VOD source is resolved via streamlink and cut with ffmpeg; both are behind
small seams so the orchestration is testable without a real Twitch VOD.
"""

import logging
import subprocess
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.channels import ensure_fresh_token
from core.models import Channel, Clip, Peak, Stream
from core.storage import ClipStorage
from core.twitch import get_videos

logger = logging.getLogger(__name__)

MAX_CLIPS = 5
# A VOD whose start is within this of the stream's start is taken to be its VOD.
VOD_MATCH_TOLERANCE = timedelta(minutes=10)
CLIP_PAD_SECONDS = 5
MIN_CLIP_SECONDS = 15
MAX_CLIP_SECONDS = 90
FFMPEG_TIMEOUT_SECONDS = 120
STREAMLINK_TIMEOUT_SECONDS = 60

# (source_url, offset_seconds, duration_seconds, out_path) -> success
Cutter = Callable[[str, int, int, Path], bool]
# stream -> the VOD's playable m3u8 URL, or None when no VOD is available yet
VodResolver = Callable[[Stream], str | None]


def clip_key(channel_id: int, stream_id: int, peak_id: int) -> str:
    return f"clips/{channel_id}/{stream_id}/{peak_id}.mp4"


def _top_peaks(db: Session, stream_id: int) -> list[Peak]:
    return list(
        db.scalars(
            select(Peak)
            .where(Peak.stream_id == stream_id)
            .order_by(Peak.score.desc())
            .limit(MAX_CLIPS)
        )
    )


def _clip_bounds(peak: Peak, stream: Stream) -> tuple[int, int]:
    """Offset into the VOD and clip duration for a peak, padded and clamped."""
    offset = int((peak.window_start - stream.started_at).total_seconds())
    offset = max(offset - CLIP_PAD_SECONDS, 0)
    span = (
        int((peak.window_end - peak.window_start).total_seconds())
        + 2 * CLIP_PAD_SECONDS
    )
    duration = max(MIN_CLIP_SECONDS, min(span, MAX_CLIP_SECONDS))
    return offset, duration


def vod_m3u8_for_stream(db: Session, stream: Stream) -> str | None:
    """Find this stream's Twitch VOD and return its playable m3u8 URL, or None
    if the VOD is not published yet (common right after a stream ends)."""
    channel = db.get(Channel, stream.channel_id)
    if channel is None:
        return None
    token = ensure_fresh_token(db, channel)
    videos = get_videos(channel.twitch_user_id, token)
    match = min(
        (v for v in videos),
        key=lambda v: abs(v.created_at - stream.started_at),
        default=None,
    )
    if match is None or abs(match.created_at - stream.started_at) > VOD_MATCH_TOLERANCE:
        logger.info("no VOD matched for clipping", extra={"stream_id": stream.id})
        return None
    return _streamlink_url(match.url)


def _streamlink_url(vod_url: str) -> str | None:
    """Resolve a twitch.tv/videos/<id> page to a direct m3u8 URL."""
    try:
        result = subprocess.run(
            ["streamlink", "--stream-url", vod_url, "best"],
            capture_output=True,
            text=True,
            timeout=STREAMLINK_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        logger.exception("streamlink failed resolving VOD url")
        return None
    url = result.stdout.strip()
    return url or None


def cut_clip(
    source_url: str, offset_seconds: int, duration_seconds: int, out_path: Path
) -> bool:
    """Cut [offset, offset+duration] from source with ffmpeg (fast input seek,
    stream copy). Returns True when a non-empty file was produced."""
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(offset_seconds),
        "-i",
        source_url,
        "-t",
        str(duration_seconds),
        "-c",
        "copy",
        "-loglevel",
        "error",
        str(out_path),
    ]
    try:
        subprocess.run(
            command, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=True
        )
    except (subprocess.SubprocessError, OSError):
        logger.exception("ffmpeg clip cut failed")
        return False
    return out_path.exists() and out_path.stat().st_size > 0


def generate_clips(
    db: Session,
    stream: Stream,
    storage: ClipStorage,
    resolver: VodResolver,
    cutter: Cutter = cut_clip,
) -> int:
    """Cut and store a clip per top peak. Best-effort: a VOD that is not ready
    or a cut that fails is skipped, never raised. Returns clips stored."""
    peaks = _top_peaks(db, stream.id)
    if not peaks:
        return 0
    source = resolver(stream)
    if source is None:
        return 0
    existing = set(db.scalars(select(Clip.peak_id).where(Clip.stream_id == stream.id)))
    stored = 0
    with tempfile.TemporaryDirectory() as workdir:
        for peak in peaks:
            if peak.id in existing:
                continue
            offset, duration = _clip_bounds(peak, stream)
            out_path = Path(workdir) / f"clip_{peak.id}.mp4"
            if not cutter(source, offset, duration, out_path):
                continue
            key = clip_key(stream.channel_id, stream.id, peak.id)
            storage.save_file(key, out_path)
            db.add(
                Clip(
                    stream_id=stream.id,
                    peak_id=peak.id,
                    offset_seconds=offset,
                    duration_seconds=duration,
                    storage_key=key,
                    score=peak.score,
                )
            )
            stored += 1
    return stored
