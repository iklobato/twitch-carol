"""Which part of each stored audio file a transcription reads.

Two capture workers record the same live, and a worker that restarts mid-live
starts a new file. Files are named by the second their audio starts, so the
transcription can line them up on the live's clock, keep every second that
was recorded once, and skip every second recorded twice."""

from datetime import UTC, datetime

import numpy as np

from workers.transcribe.segments import AudioCoverage, SegmentNameParser

SAMPLE_RATE = 16_000
LIVE_START = datetime(2026, 11, 10, 20, 0, 0, tzinfo=UTC)
LIVE_START_EPOCH = int(LIVE_START.timestamp())
TEN_MINUTES = 600.0
LEGACY_SEQUENCE = 3
STANDBY_STARTED_AFTER = 192
STANDBY_LAG = 3.0
CRASH_AFTER = 330.0
BACK_AFTER = 335.0
SECOND_COPY_FROM = 300.0
SECOND_COPY_LENGTH = 300.0
ONLY_IN_SECOND_COPY = SECOND_COPY_FROM + SECOND_COPY_LENGTH - CRASH_AFTER


class Recording:
    """Silent audio of a given length, standing in for a decoded file."""

    def seconds(self, length: float) -> np.ndarray:
        return np.zeros(int(length * SAMPLE_RATE), dtype=np.float32)


def test_clock_named_file_sits_at_its_start_second_in_the_live() -> None:
    key = f"audio/1/2/{LIVE_START_EPOCH + STANDBY_STARTED_AFTER}-standby.ogg"

    offset = SegmentNameParser().parse(key).offset_seconds(LIVE_START)

    assert offset == STANDBY_STARTED_AFTER, f"file started 192s into the live, got {offset}"


def test_legacy_numbered_file_keeps_its_old_position() -> None:
    key = f"audio/1/2/{LEGACY_SEQUENCE:03d}.ogg"

    offset = SegmentNameParser().parse(key).offset_seconds(LIVE_START)

    assert offset == LEGACY_SEQUENCE * TEN_MINUTES, f"legacy file 003 moved to {offset}"


def test_second_copy_of_the_same_minutes_is_skipped() -> None:
    coverage = AudioCoverage(SAMPLE_RATE)
    coverage.new_part(0.0, Recording().seconds(TEN_MINUTES))

    duplicate = coverage.new_part(STANDBY_LAG, Recording().seconds(TEN_MINUTES - STANDBY_LAG))

    assert duplicate is None, "the standby copy of minutes already read was transcribed again"


def test_restart_keeps_both_halves_of_the_window() -> None:
    coverage = AudioCoverage(SAMPLE_RATE)
    coverage.new_part(0.0, Recording().seconds(CRASH_AFTER))

    after_restart = coverage.new_part(BACK_AFTER, Recording().seconds(TEN_MINUTES - BACK_AFTER))

    assert after_restart is not None, "audio recorded after a restart was dropped"
    assert after_restart.offset_seconds == BACK_AFTER, "restart audio landed at the wrong time"


def test_overlapping_copy_contributes_only_the_part_not_yet_read() -> None:
    coverage = AudioCoverage(SAMPLE_RATE)
    coverage.new_part(0.0, Recording().seconds(CRASH_AFTER))

    tail = coverage.new_part(SECOND_COPY_FROM, Recording().seconds(SECOND_COPY_LENGTH))

    assert tail is not None, "the part only the second copy holds was dropped"
    kept = (tail.offset_seconds, len(tail.samples) / SAMPLE_RATE)
    assert kept == (CRASH_AFTER, ONLY_IN_SECOND_COPY), f"kept {kept}"
