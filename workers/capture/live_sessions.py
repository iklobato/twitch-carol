"""The capture sessions one worker runs, kept in step with the database.

A stream leaves the "capturing" list in two ways: this worker finalized it, or
another capture worker did (the standby and the official worker run on the same
lives). A session whose stream left the list for either reason has to stop, or
it stays on the channel's chat and writes the next live into the old row.
"""

from core.models import Channel, Stream
from workers.capture.session import CaptureSession

StreamRows = list[tuple[Stream, Channel]]


class LiveSessions:
    def __init__(self, sessions: dict[int, CaptureSession]) -> None:
        self._sessions = sessions

    def open_new(self, rows: StreamRows) -> list[CaptureSession]:
        """Sessions for streams on air that this worker is not capturing yet."""
        opened: list[CaptureSession] = []
        for stream, channel in rows:
            if stream.ended_at is not None or stream.id in self._sessions:
                continue
            session = CaptureSession.for_live(stream, channel)
            self._sessions[stream.id] = session
            opened.append(session)
        return opened

    def closing(self, rows: StreamRows) -> list[CaptureSession]:
        """Sessions to stop and finalize: streams that ended, and streams that
        another worker already finalized."""
        ended = [self._session_for(stream, channel) for stream, channel in rows if stream.ended_at]
        listed = {stream.id for stream, _ in rows}
        gone = [
            self._sessions.pop(stream_id)
            for stream_id in list(self._sessions)
            if stream_id not in listed
        ]
        return ended + gone

    def _session_for(self, stream: Stream, channel: Channel) -> CaptureSession:
        if stream.id in self._sessions:
            return self._sessions.pop(stream.id)
        # Worker restarted mid-live: no collector stats, audit from DB only.
        return CaptureSession.for_live(stream, channel)
