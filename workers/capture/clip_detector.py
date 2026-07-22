"""Online best-moment detector for live auto-clipping.

Pure logic: the chat collector feeds message timestamps as they arrive; a
chat-rate spike over the rolling baseline (with a cooldown and a per-stream cap)
marks a clip-worthy moment. Twitch can only clip the live moment, so detection
has to be online, not the post-stream SQL peaks.
"""

from collections import deque

WINDOW_SECONDS = 30.0
BASELINE_SECONDS = 300.0
SPIKE_LIFT = 3.0
MIN_WINDOW_MESSAGES = 15
COOLDOWN_SECONDS = 120.0
MAX_CLIPS_PER_STREAM = 10


class ClipDetector:
    """Flags a moment when the last WINDOW_SECONDS of chat exceeds SPIKE_LIFT x
    the rolling baseline rate, gated by a minimum absolute count (so quiet
    channels don't clip on noise), a cooldown, and a per-stream cap."""

    def __init__(
        self,
        window_seconds: float = WINDOW_SECONDS,
        baseline_seconds: float = BASELINE_SECONDS,
        spike_lift: float = SPIKE_LIFT,
        min_window_messages: int = MIN_WINDOW_MESSAGES,
        cooldown_seconds: float = COOLDOWN_SECONDS,
        max_clips: int = MAX_CLIPS_PER_STREAM,
    ) -> None:
        self._window = window_seconds
        self._baseline = baseline_seconds
        self._lift = spike_lift
        self._min_window = min_window_messages
        self._cooldown = cooldown_seconds
        self._max_clips = max_clips
        self._times: deque[float] = deque()
        self._last_clip_at: float | None = None
        self._clips = 0

    def observe(self, now: float) -> None:
        self._times.append(now)
        cutoff = now - self._baseline
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def should_clip(self, now: float) -> bool:
        if self._clips >= self._max_clips:
            return False
        if self._last_clip_at is not None and now - self._last_clip_at < self._cooldown:
            return False
        window_start = now - self._window
        window_count = sum(1 for t in self._times if t >= window_start)
        if window_count < self._min_window:
            return False
        windows_in_baseline = self._baseline / self._window
        baseline_rate = len(self._times) / windows_in_baseline
        return window_count >= baseline_rate * self._lift

    def window_rate(self, now: float) -> int:
        return sum(1 for t in self._times if t >= now - self._window)

    def mark_clipped(self, now: float) -> None:
        self._last_clip_at = now
        self._clips += 1
