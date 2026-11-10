"""Online chat-spike detector for live auto-clipping."""

from core.config import CaptureRole
from workers.capture.clip_detector import ClipDetector, SpikeDetector, SpikeDetectorFactory

BURST_AT = 290.0
BURST_MESSAGES = 40
BASELINE_END = 270
BASELINE_STEP = 30


def _detector(**over: object) -> ClipDetector:
    params: dict[str, object] = {
        "window_seconds": 10,
        "baseline_seconds": 100,
        "spike_lift": 3.0,
        "min_window_messages": 5,
        "cooldown_seconds": 30,
        "max_clips": 3,
    }
    params.update(over)
    return ClipDetector(**params)  # type: ignore[arg-type]


def test_burst_over_baseline_triggers_clip() -> None:
    d = _detector()
    for i in range(10):  # sparse baseline: 10 msgs spread across 90s
        d.observe(i * 9.0)
    now = 95.0
    for _ in range(8):  # burst in the last window
        d.observe(now)
    assert d.should_clip(now) is True


def test_small_channel_below_min_does_not_clip() -> None:
    d = _detector(min_window_messages=5)
    d.observe(0.0)
    now = 50.0
    for _ in range(3):  # a "spike" of 3 is still under the absolute floor
        d.observe(now)
    assert d.should_clip(now) is False


def test_cooldown_blocks_second_clip() -> None:
    d = _detector(cooldown_seconds=30)
    for _ in range(8):
        d.observe(50.0)
    assert d.should_clip(50.0) is True
    d.mark_clipped(50.0)
    for _ in range(8):
        d.observe(60.0)  # another burst, but within the cooldown
    assert d.should_clip(60.0) is False


def test_cap_blocks_after_max() -> None:
    d = _detector(max_clips=1)
    for _ in range(8):
        d.observe(50.0)
    assert d.should_clip(50.0) is True
    d.mark_clipped(50.0)
    for _ in range(8):  # long past the cooldown, but the cap is reached
        d.observe(500.0)
    assert d.should_clip(500.0) is False


class ChatBurst:
    """A quiet baseline then a burst far over it: a clip-worthy moment."""

    def play(self, detector: SpikeDetector) -> float:
        for second in range(0, BASELINE_END, BASELINE_STEP):
            detector.observe(float(second))
        for _ in range(BURST_MESSAGES):
            detector.observe(BURST_AT)
        return BURST_AT


def test_official_worker_clips_a_chat_spike() -> None:
    detector = SpikeDetectorFactory().for_role(CaptureRole.PRIMARY)

    now = ChatBurst().play(detector)

    assert detector.should_clip(now) is True, "the official worker must clip a spike"


def test_standby_worker_never_clips_the_same_spike() -> None:
    detector = SpikeDetectorFactory().for_role(CaptureRole.STANDBY)

    now = ChatBurst().play(detector)

    assert detector.should_clip(now) is False, "a standby clip would duplicate it on Twitch"
