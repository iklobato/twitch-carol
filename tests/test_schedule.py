from datetime import UTC, datetime, timedelta

from core.schedule import estimate_next_live


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=UTC)


def test_no_history_falls_back_to_24h() -> None:
    now = _dt(11, 12)
    assert estimate_next_live(now, []) == now + timedelta(hours=24)


def test_recurring_weekday_pattern() -> None:
    # Streams every Monday (2026-06-29, 07-06) around 20:00 UTC
    history = [_dt(6, 20), datetime(2026, 6, 29, 20, 0, tzinfo=UTC)]
    now = _dt(11, 12)  # Saturday
    estimate = estimate_next_live(now, history)
    assert estimate == datetime(2026, 7, 13, 20, 0, tzinfo=UTC)  # next Monday 20:00


def test_same_day_later_hour_is_chosen() -> None:
    # History on Saturdays at 22:00; now is Saturday noon -> today 22:00
    history = [_dt(4, 22)]  # 2026-07-04 was a Saturday
    now = _dt(11, 12)  # Saturday
    assert estimate_next_live(now, history) == _dt(11, 22)


def test_median_of_start_times() -> None:
    # Saturdays at 19:00, 20:00 and 21:00 -> median 20:00
    history = [
        datetime(2026, 6, 20, 19, 0, tzinfo=UTC),
        datetime(2026, 6, 27, 20, 0, tzinfo=UTC),
        _dt(4, 21),
    ]
    now = _dt(11, 12)
    assert estimate_next_live(now, history) == _dt(11, 20)


def test_urgency_ordering_for_queue() -> None:
    """The channel whose next live is sooner must sort first."""
    now = _dt(11, 12)
    soon = estimate_next_live(now, [_dt(4, 14)])  # Saturdays 14:00 -> today
    late = estimate_next_live(
        now, [datetime(2026, 7, 8, 20, 0, tzinfo=UTC)]
    )  # Wednesdays
    assert soon < late
