from datetime import UTC, datetime, timedelta

from workers.analyze.peaks import detect_peaks


def _buckets(counts: list[int]) -> list[tuple[datetime, int]]:
    base = datetime(2026, 7, 11, 20, 0, tzinfo=UTC)
    return [(base + timedelta(minutes=i), count) for i, count in enumerate(counts)]


def test_flat_chat_has_no_peaks() -> None:
    assert detect_peaks(_buckets([5, 6, 5, 6, 5, 6])) == []


def test_empty_stream_has_no_peaks() -> None:
    assert detect_peaks([]) == []


def test_burst_becomes_single_merged_window() -> None:
    peaks = detect_peaks(_buckets([5, 5, 30, 40, 5, 5]))
    assert len(peaks) == 1
    peak = peaks[0]
    assert peak.start.minute == 2
    assert peak.end.minute == 4  # two adjacent buckets merged
    assert peak.score == 40 / 5


def test_peaks_ranked_by_score_and_limited() -> None:
    counts = [5] * 20
    counts[2] = 30
    counts[6] = 90
    counts[10] = 50
    counts[14] = 40
    counts[16] = 35
    counts[18] = 32
    peaks = detect_peaks(_buckets(counts), top_n=5)
    assert len(peaks) == 5
    assert [round(p.score) for p in peaks] == [18, 10, 8, 7, 6]


def test_small_stream_noise_is_ignored() -> None:
    # lift is high (3x) but absolute volume is under the floor
    assert detect_peaks(_buckets([2, 2, 6, 2, 2])) == []
