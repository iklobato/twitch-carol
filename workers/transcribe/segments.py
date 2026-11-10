"""Where each stored audio file sits in the live, and which part of it is new.

Capture names a file by the second its audio starts and the worker role
(`1794277890-primary.ogg`), cutting on the wall clock every 10 minutes. Two
workers on the same live therefore store two copies of most windows, and a
worker that restarts mid-live stores two pieces of one window. Reading the
files in start order and keeping only the seconds not yet covered transcribes
every recorded second exactly once.

Files stored before this naming are numbered per worker process (`000.ogg`,
`001.ogg`); they keep the old position, sequence x 10 minutes.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Protocol

import numpy as np

from core.storage import SEGMENT_ROLE_SEPARATOR
from workers.capture.collectors import AUDIO_SEGMENT_SECONDS

NO_COVERAGE = float("-inf")
# Two workers cut the same clock boundary a few packets apart; less new audio
# than this is that jitter, not a gap worth transcribing.
MIN_NEW_SECONDS = 1.0


class SegmentName(Protocol):
    def offset_seconds(self, started_at: datetime) -> float: ...


@dataclass(frozen=True)
class SequenceName:
    sequence: int

    def offset_seconds(self, started_at: datetime) -> float:
        return float(self.sequence * AUDIO_SEGMENT_SECONDS)


@dataclass(frozen=True)
class ClockName:
    epoch: int

    def offset_seconds(self, started_at: datetime) -> float:
        return self.epoch - started_at.timestamp()


class SegmentNameParser:
    def parse(self, key: str) -> SegmentName:
        stem = PurePosixPath(key).stem
        if SEGMENT_ROLE_SEPARATOR in stem:
            return ClockName(int(stem.split(SEGMENT_ROLE_SEPARATOR, 1)[0]))
        return SequenceName(int(stem))


@dataclass(frozen=True)
class AudioPiece:
    offset_seconds: float
    samples: np.ndarray


class AudioCoverage:
    """Fed files in start order; returns only the audio past what earlier files
    already covered, or None when a file adds nothing new."""

    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        self._covered_until = NO_COVERAGE

    def new_part(self, start: float, samples: np.ndarray) -> AudioPiece | None:
        end = start + len(samples) / self._sample_rate
        if end <= self._covered_until + MIN_NEW_SECONDS:
            return None
        new_start = max(start, self._covered_until)
        self._covered_until = end
        first_sample = int((new_start - start) * self._sample_rate)
        return AudioPiece(offset_seconds=new_start, samples=samples[first_sample:])
