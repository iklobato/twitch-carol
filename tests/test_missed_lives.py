"""A live whose stream.online webhook never arrived still gets captured.

The webhook is the only thing that opens a stream row. When the API is down or
the callback fails as a streamer goes live, no capture worker sees the live at
all. The capture worker now asks Helix every minute which channels are live and
opens the row itself."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Stream, StreamStatus
from core.twitch import LiveStream
from tests.factories import make_channel, make_stream
from workers.capture.missed_lives import MissedLiveFinder

LIVE_FOR_MINUTES = 7


class FakeHelix:
    """Answers Get Streams from a fixed list of channels that are live."""

    def __init__(self, live: list[LiveStream]) -> None:
        self._live = live

    def live(self, user_ids: list[int]) -> list[LiveStream]:
        return [stream for stream in self._live if int(stream.user_id) in user_ids]


class OnAir:
    """A Helix answer for one channel that went live a few minutes ago."""

    def since(self, twitch_user_id: int) -> LiveStream:
        started = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=LIVE_FOR_MINUTES)
        return LiveStream(user_id=str(twitch_user_id), started_at=started)


def test_live_with_no_webhook_gets_a_capturing_stream(db: Session) -> None:
    channel = make_channel(db)
    live = OnAir().since(channel.twitch_user_id)

    MissedLiveFinder(FakeHelix([live])).open_missed(db)

    stream = db.scalar(select(Stream).where(Stream.channel_id == channel.id))
    assert stream is not None, "a channel live on Twitch got no stream row"
    assert (stream.status, stream.started_at) == (StreamStatus.CAPTURING, live.started_at)


def test_live_already_being_captured_is_left_alone(db: Session) -> None:
    channel = make_channel(db)
    make_stream(db, channel, status=StreamStatus.CAPTURING, duration_minutes=None)

    MissedLiveFinder(FakeHelix([OnAir().since(channel.twitch_user_id)])).open_missed(db)

    rows = db.scalar(
        select(func.count()).select_from(Stream).where(Stream.channel_id == channel.id)
    )
    assert rows == 1, f"a live already being captured got {rows} stream rows"


def test_live_that_already_ended_here_is_not_opened_again(db: Session) -> None:
    """Twitch can still list a live for a minute after stream.offline closed it."""
    channel = make_channel(db)
    live = OnAir().since(channel.twitch_user_id)
    ended = make_stream(db, channel, status=StreamStatus.READY)
    ended.started_at = live.started_at
    db.flush()

    MissedLiveFinder(FakeHelix([live])).open_missed(db)

    rows = db.scalar(
        select(func.count()).select_from(Stream).where(Stream.channel_id == channel.id)
    )
    assert rows == 1, "the live that just ended was reopened as a second stream"


def test_offline_channel_gets_nothing(db: Session) -> None:
    make_channel(db)

    opened = MissedLiveFinder(FakeHelix([])).open_missed(db)

    assert opened == [], f"an offline channel got {len(opened)} stream rows"
