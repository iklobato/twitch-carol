"""Which capture sessions a worker opens and closes on each poll.

Regression found running a primary and a standby worker on one simulated live
(2026-11-10): the standby finalized the stream first, the stream left the
"capturing" list, and the primary never stopped its own session. In production
that session would stay on the channel's IRC forever and write the streamer's
next live into the old stream row."""

from datetime import UTC, datetime

from core.models import Channel, Stream
from workers.capture.live_sessions import LiveSessions

STREAM_ID = 20
CHANNEL_ID = 4


class Live:
    """Unsaved stream and channel rows, as the capture poll returns them."""

    def on_air(self) -> tuple[Stream, Channel]:
        channel = Channel(id=CHANNEL_ID, login="sim_streamer", twitch_user_id=CHANNEL_ID)
        stream = Stream(id=STREAM_ID, channel_id=CHANNEL_ID, started_at=datetime.now(UTC))
        return stream, channel

    def ended(self) -> tuple[Stream, Channel]:
        stream, channel = self.on_air()
        stream.ended_at = datetime.now(UTC)
        return stream, channel


def test_session_closes_when_another_worker_finalized_the_stream() -> None:
    sessions = LiveSessions({})
    sessions.open_new([Live().on_air()])

    closing = sessions.closing([])

    assert [session.stream_id for session in closing] == [STREAM_ID], (
        "a stream finalized by the standby left this worker's session running"
    )


def test_ended_stream_closes_the_running_session_once() -> None:
    sessions = LiveSessions({})
    sessions.open_new([Live().on_air()])

    first = sessions.closing([Live().ended()])
    second = sessions.closing([])

    assert (len(first), len(second)) == (1, 0), f"closed {len(first)} then {len(second)}"


def test_running_session_is_not_opened_twice() -> None:
    sessions = LiveSessions({})
    sessions.open_new([Live().on_air()])

    reopened = sessions.open_new([Live().on_air()])

    assert reopened == [], "a second session would capture the same live twice in one worker"
