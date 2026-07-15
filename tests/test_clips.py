"""Auto-clips: peak-window bounds, ffmpeg cutting, and clip orchestration."""

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from core.clips import _clip_bounds, cut_clip, generate_clips
from core.models import Clip
from tests.factories import add_peak, make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class FakeStorage:
    """Records save_file calls; the object store seam for tests."""

    def __init__(self) -> None:
        self.saved: dict[str, int] = {}

    def save_file(self, key: str, local_path: Path) -> None:
        self.saved[key] = local_path.stat().st_size

    def list_keys(self, prefix: str) -> list[str]:
        return [k for k in self.saved if k.startswith(prefix)]

    def fetch_file(self, key: str, destination: Path) -> None: ...

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str | None:
        return f"https://cdn/{key}"


def _synthetic_video(path: Path, seconds: int = 30) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=320x240:rate=15",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-loglevel",
            "error",
            str(path),
        ],
        check=True,
    )


def test_clip_bounds_pads_and_clamps(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    peak = add_peak(db, stream, offset_seconds=300, score=5.0)  # 60s window at +300s

    offset, duration = _clip_bounds(peak, stream)
    assert offset == 300 - 5  # padded back by CLIP_PAD_SECONDS
    assert duration == 60 + 2 * 5  # window + padding on both sides


def test_clip_bounds_offset_never_negative(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    peak = add_peak(db, stream, offset_seconds=2, score=1.0)
    offset, _ = _clip_bounds(peak, stream)
    assert offset == 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_cut_clip_produces_a_file(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    _synthetic_video(source, seconds=30)
    out = tmp_path / "clip.mp4"

    assert cut_clip(str(source), offset_seconds=5, duration_seconds=10, out_path=out)
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_generate_clips_cuts_stores_and_is_idempotent(db, tmp_path: Path) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_peak(db, stream, offset_seconds=5, score=9.0)
    add_peak(db, stream, offset_seconds=15, score=8.0)
    db.flush()

    source = tmp_path / "vod.mp4"
    _synthetic_video(source, seconds=40)
    storage = FakeStorage()

    def resolver(_stream):
        return str(source)

    stored = generate_clips(db, stream, storage, resolver)
    db.flush()
    assert stored == 2
    clips = db.scalars(select(Clip).where(Clip.stream_id == stream.id)).all()
    assert len(clips) == 2
    assert all(c.storage_key in storage.saved for c in clips)
    assert all(storage.saved[c.storage_key] > 0 for c in clips)

    # re-running does not duplicate (existing peak_ids are skipped)
    again = generate_clips(db, stream, storage, resolver)
    db.flush()
    assert again == 0


def test_generate_clips_no_vod_stores_nothing(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_peak(db, stream, offset_seconds=5, score=9.0)
    db.flush()

    def no_vod(_stream):
        return None

    assert generate_clips(db, stream, FakeStorage(), no_vod) == 0
    assert db.scalars(select(Clip).where(Clip.stream_id == stream.id)).all() == []
