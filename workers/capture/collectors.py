"""Capture collectors: chat (IRC or simulated), viewer sampler, audio recorder.

Simulation (SIMULATION=1) swaps only the outermost source (socket/Helix/HLS)
for Valkey-fed fakes; parsing, buffering and persistence are the same code.
Sim sources: raw IRC lines in stream sim:irc:{login}, viewer count in key
sim:viewers:{login}, input audio path in key sim:audio:{login}.
"""

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.channels import ensure_fresh_token
from core.config import get_settings
from core.db import ensure_chat_partition, session_factory
from core.irc import (
    IRC_HOST,
    IRC_PORT,
    ParsedChat,
    anonymous_nick,
    backoff_delays,
    parse_privmsg,
)
from core.models import Channel, ChatMessage, Stream, TwitchClip, ViewerSample
from core.queues import get_valkey
from core.storage import SEGMENT_ROLE_SEPARATOR, audio_key, get_audio_storage
from core.streams import mark_stream_offline
from core.twitch import TwitchAuthError, create_clip, get_stream_info
from workers.capture.clip_detector import SpikeDetector

logger = logging.getLogger(__name__)

CHAT_FLUSH_INTERVAL_SECONDS = 2.0
VIEWER_SAMPLE_INTERVAL_SECONDS = 60.0
# Helix reporting the channel offline is the backstop for a lost stream.offline
# webhook: without it a capture runs forever (the stream stays CAPTURING, the
# dashboard shows a ghost live, and the next real live gets glued onto the stale
# row because start_stream is idempotent per channel). Three consecutive polls
# (~3 min) so a transient empty Helix response never kills a live capture.
OFFLINE_SAMPLES_TO_END = 3
SIM_POLL_BLOCK_MS = 1000
AUDIO_SEGMENT_SECONDS = 600
OPUS_BITRATE = "32k"
# Cut on the wall clock and name each file by its start second (epoch), so the
# standby worker's copy of a window lines up with the official one and a
# restarted worker never reuses a name.
CLOCK_SEGMENT_ARGS = ("-segment_atclocktime", "1", "-strftime", "1")
CLOCK_SEGMENT_PATTERN = "%s.ogg"


class ChatCollector:
    def __init__(self, stream: Stream, channel: Channel, clips: SpikeDetector) -> None:
        self._stream_id = stream.id
        self._channel_id = channel.id
        self._login = channel.login
        self._broadcaster_id = channel.twitch_user_id
        self._buffer: list[ParsedChat] = []
        self._ensured_months: set[date] = set()
        self._clips = clips
        self._clip_tasks: set[asyncio.Task] = set()
        self.stats = {"messages": 0, "disconnects": 0, "gap_seconds": 0.0}

    async def run(self, stop: asyncio.Event) -> None:
        flusher = asyncio.create_task(self._flush_loop(stop))
        try:
            if get_settings().simulation:
                await self._consume_simulated(stop)
            else:
                await self._consume_irc(stop)
        finally:
            flusher.cancel()
            await asyncio.gather(flusher, return_exceptions=True)
            await asyncio.to_thread(self.flush)

    async def _consume_irc(self, stop: asyncio.Event) -> None:
        delays = backoff_delays()
        while not stop.is_set():
            disconnected_at = datetime.now(UTC)
            try:
                await self._read_connection(stop)
                delays = backoff_delays()
            except (OSError, asyncio.IncompleteReadError):
                self.stats["disconnects"] += 1
                delay = next(delays)
                self.stats["gap_seconds"] += (
                    datetime.now(UTC) - disconnected_at
                ).total_seconds() + delay
                logger.warning(
                    "irc disconnected, reconnecting in %.1fs",
                    delay,
                    extra={
                        "stream_id": self._stream_id,
                        "channel_id": self._channel_id,
                    },
                )
                await asyncio.sleep(delay)

    async def _read_connection(self, stop: asyncio.Event) -> None:
        reader, writer = await asyncio.open_connection(IRC_HOST, IRC_PORT)
        handshake = (
            f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
            f"NICK {anonymous_nick()}\r\n"
            f"JOIN #{self._login}\r\n"
        )
        writer.write(handshake.encode())
        await writer.drain()
        try:
            while not stop.is_set():
                raw = await asyncio.wait_for(reader.readline(), timeout=30.0)
                if not raw:
                    raise ConnectionResetError("irc connection closed")
                line = raw.decode("utf-8", errors="replace")
                if line.startswith("PING"):
                    writer.write(b"PONG :tmi.twitch.tv\r\n")
                    await writer.drain()
                    continue
                self.ingest(line)
                self._maybe_clip()
        except TimeoutError:
            writer.write(b"PING :keepalive\r\n")
            await writer.drain()
        finally:
            writer.close()

    async def _consume_simulated(self, stop: asyncio.Event) -> None:
        stream_key = f"sim:irc:{self._login}"
        last_id = "0"
        while not stop.is_set():
            entries = await asyncio.to_thread(
                self._read_sim_entries, stream_key, last_id
            )
            for entry_id, fields in entries:
                last_id = entry_id
                self.ingest(fields["line"])

    @staticmethod
    def _read_sim_entries(
        stream_key: str, last_id: str
    ) -> list[tuple[str, dict[str, str]]]:
        # redis-py types xread as an opaque ResponseT; with decode_responses=True
        # it is [(stream_name, [(entry_id, fields)])].
        response = cast(
            list[tuple[str, list[tuple[str, dict[str, str]]]]],
            get_valkey().xread({stream_key: last_id}, None, SIM_POLL_BLOCK_MS),
        )
        if not response:
            return []
        return [
            (entry_id, fields) for _, items in response for entry_id, fields in items
        ]

    def ingest(self, line: str) -> None:
        parsed = parse_privmsg(line)
        if parsed is None:
            return
        self._buffer.append(parsed)
        self._clips.observe(time.monotonic())

    def _maybe_clip(self) -> None:
        """Fire-and-forget a Twitch clip when chat spikes. Best-effort: clipping
        needs the broadcaster live + the clips:edit scope, and any failure must
        never disturb the capture, so it runs off the ingest path."""
        now = time.monotonic()
        if not self._clips.should_clip(now):
            return
        rate = self._clips.window_rate(now)
        self._clips.mark_clipped(now)
        task = asyncio.create_task(
            asyncio.to_thread(self._create_and_store_clip, f"chat spike ({rate})")
        )
        self._clip_tasks.add(task)
        task.add_done_callback(self._clip_tasks.discard)

    def _create_and_store_clip(self, reason: str) -> None:
        try:
            with session_factory()() as db:
                channel = db.get(Channel, self._channel_id)
                if channel is None:
                    return
                token = ensure_fresh_token(db, channel)
                clip = create_clip(self._broadcaster_id, token)
                db.add(
                    TwitchClip(
                        stream_id=self._stream_id,
                        channel_id=self._channel_id,
                        clip_id=clip.id,
                        edit_url=clip.edit_url,
                        reason=reason,
                    )
                )
                db.commit()
                logger.info(
                    "auto-clip created (%s)",
                    reason,
                    extra={"stream_id": self._stream_id, "clip_id": clip.id},
                )
        except (TwitchAuthError, OSError) as err:
            logger.warning(
                "auto-clip failed: %s",
                err,
                extra={"stream_id": self._stream_id, "channel_id": self._channel_id},
            )

    async def _flush_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(CHAT_FLUSH_INTERVAL_SECONDS)
            await asyncio.to_thread(self.flush)

    def flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        with session_factory()() as db:
            self._ensure_partitions(db, batch)
            # A standby worker on the same live sends the same messages: the
            # copy that arrives second is dropped by the unique message id.
            inserted = db.execute(
                insert(ChatMessage)
                .values([self._row(message) for message in batch])
                .on_conflict_do_nothing(index_elements=["message_id", "sent_at"])
            )
            db.commit()
        self.stats["messages"] += cast(CursorResult, inserted).rowcount

    def _ensure_partitions(self, db: Session, batch: list[ParsedChat]) -> None:
        months = {message.sent_at.date().replace(day=1) for message in batch}
        for month in months - self._ensured_months:
            ensure_chat_partition(db, month)
            self._ensured_months.add(month)

    def _row(self, message: ParsedChat) -> dict:
        return {
            "stream_id": self._stream_id,
            "channel_id": self._channel_id,
            "sent_at": message.sent_at,
            "message_id": message.message_id,
            "author_id": message.author_id,
            "author_login": message.author_login,
            "badges": message.badges,
            "emotes": message.emotes,
            "text": message.text,
        }


class ViewerSampler:
    def __init__(self, stream: Stream, channel: Channel) -> None:
        self._stream_id = stream.id
        self._channel_id = channel.id
        self._twitch_user_id = channel.twitch_user_id
        self._login = channel.login
        self._title_recorded = False
        self._offline_since: datetime | None = None
        self._offline_samples = 0
        self.stats = {"samples": 0}

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.sample_once)
            except TwitchAuthError:
                logger.exception(
                    "viewer sample failed", extra={"stream_id": self._stream_id}
                )
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=VIEWER_SAMPLE_INTERVAL_SECONDS
                )
            except TimeoutError:
                continue

    def sample_once(self) -> None:
        count, title, category = self._read_source()
        if count is None:
            self._note_offline()
            return
        self._offline_since = None
        self._offline_samples = 0
        with session_factory()() as db:
            self._store_sample(db, count)
            self._record_title(db, title, category)
            db.commit()
        self.stats["samples"] += 1

    def _store_sample(self, db: Session, count: int) -> None:
        # Cut to the minute: a standby worker sampling the same minute writes
        # the same key, and its copy is dropped.
        db.execute(
            insert(ViewerSample)
            .values(
                stream_id=self._stream_id,
                sampled_at=datetime.now(UTC).replace(second=0, microsecond=0),
                viewer_count=count,
            )
            .on_conflict_do_nothing(index_elements=["stream_id", "sampled_at"])
        )

    def _record_title(self, db: Session, title: str | None, category: str | None) -> None:
        if title is None or self._title_recorded:
            return
        stream = db.get(Stream, self._stream_id)
        if stream is None:
            return
        stream.title = title
        stream.category = category
        self._title_recorded = True

    def _note_offline(self) -> None:
        """Helix says the channel is offline. The stream.offline webhook is not
        guaranteed (it is lost whenever the callback is down), so after
        OFFLINE_SAMPLES_TO_END consecutive offline polls we end the stream from
        here. Goes through the same mark_stream_offline the webhook uses, so the
        worker finalizes the session on its next poll exactly as it always does.
        ended_at is the first offline poll, not now, so a capture that only
        notices late still records the real end.
        """
        self._offline_samples += 1
        if self._offline_since is None:
            self._offline_since = datetime.now(UTC)
        if self._offline_samples < OFFLINE_SAMPLES_TO_END:
            return
        with session_factory()() as db:
            stream = db.get(Stream, self._stream_id)
            if stream is None or stream.ended_at is not None:
                return
            mark_stream_offline(db, stream, self._offline_since)
            db.commit()
        logger.info(
            "stream ended from Helix polling (stream.offline webhook missed)",
            extra={"stream_id": self._stream_id, "channel_id": self._channel_id},
        )

    def _read_source(self) -> tuple[int | None, str | None, str | None]:
        if get_settings().simulation:
            raw = get_valkey().get(f"sim:viewers:{self._login}")
            return (int(raw), None, None) if raw is not None else (None, None, None)
        info = get_stream_info(self._twitch_user_id)
        if info is None:
            return (None, None, None)
        return (info.viewer_count, info.title, info.game_name)


class AudioRecorder:
    def __init__(self, stream: Stream, channel: Channel) -> None:
        self._stream_id = stream.id
        self._channel_id = channel.id
        self._login = channel.login
        self.stats = {"segments": 0}

    async def run(self, stop: asyncio.Event) -> None:
        try:
            if get_settings().simulation:
                await self._record_simulated(stop)
            else:
                await self._record_hls(stop)
        except (OSError, subprocess.SubprocessError):
            logger.exception(
                "audio recorder failed", extra={"stream_id": self._stream_id}
            )

    def _read_sim_audio_path(self) -> str | None:
        value = get_valkey().get(f"sim:audio:{self._login}")
        return str(value) if value is not None else None

    async def _record_simulated(self, stop: asyncio.Event) -> None:
        source: str | None = None
        while not stop.is_set() and source is None:
            source = await asyncio.to_thread(self._read_sim_audio_path)
            if source is None:
                await asyncio.sleep(1.0)
        if source is None:
            return
        with tempfile.TemporaryDirectory() as workdir:
            command = self._ffmpeg_segment_command(["-i", source], Path(workdir))
            process = await asyncio.create_subprocess_exec(
                *command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            await process.wait()
            await asyncio.to_thread(self._upload_segments, Path(workdir))

    async def _record_hls(self, stop: asyncio.Event) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            # os.pipe wires streamlink stdout to ffmpeg stdin: asyncio
            # subprocesses accept raw fds, not each other's StreamReaders.
            read_fd, write_fd = os.pipe()
            streamlink = await asyncio.create_subprocess_exec(
                "streamlink",
                "--twitch-disable-ads",
                "--stdout",
                f"twitch.tv/{self._login}",
                "audio_only",
                stdout=write_fd,
                stderr=subprocess.DEVNULL,
            )
            os.close(write_fd)
            command = self._ffmpeg_segment_command(["-i", "pipe:0"], Path(workdir))
            ffmpeg = await asyncio.create_subprocess_exec(
                *command,
                stdin=read_fd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.close(read_fd)
            uploaded: set[Path] = set()
            while not stop.is_set() and ffmpeg.returncode is None:
                await asyncio.sleep(5.0)
                await asyncio.to_thread(
                    self._upload_segments, Path(workdir), uploaded, True
                )
            for process in (streamlink, ffmpeg):
                if process.returncode is None:
                    process.terminate()
            await asyncio.gather(
                streamlink.wait(), ffmpeg.wait(), return_exceptions=True
            )
            await asyncio.to_thread(self._upload_segments, Path(workdir), uploaded)

    def _ffmpeg_segment_command(
        self, input_args: list[str], workdir: Path
    ) -> list[str]:
        return [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            *input_args,
            "-vn",
            "-c:a",
            "libopus",
            "-b:a",
            OPUS_BITRATE,
            "-f",
            "segment",
            "-segment_time",
            str(AUDIO_SEGMENT_SECONDS),
            *CLOCK_SEGMENT_ARGS,
            str(workdir / CLOCK_SEGMENT_PATTERN),
        ]

    def _upload_segments(
        self, workdir: Path, uploaded: set[Path] | None = None, keep_last: bool = False
    ) -> None:
        """keep_last skips the newest file, which ffmpeg is still writing."""
        done = uploaded if uploaded is not None else set()
        segments = sorted(workdir.glob("*.ogg"))
        if keep_last and segments:
            segments = segments[:-1]
        storage = get_audio_storage()
        for path in segments:
            if path in done:
                continue
            name = f"{path.stem}{SEGMENT_ROLE_SEPARATOR}{get_settings().capture_role}"
            storage.save_file(audio_key(self._channel_id, self._stream_id, name), path)
            done.add(path)
            self.stats["segments"] += 1
            logger.info(
                "audio segment stored",
                extra={"stream_id": self._stream_id, "channel_id": self._channel_id},
            )
