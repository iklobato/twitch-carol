"""Weekly recap digest: week boundaries, folded totals and the rendered body."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from core.models import InsightType, StreamRecord, TwitchClip
from core.records import RecordMetric
from core.weekly import build_week, last_week_bounds, render_html
from tests.factories import (
    add_chat,
    add_event,
    add_insight,
    add_peak,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

NOW = datetime.now(UTC)
# A window in the recent past: inside the +/-31d chat partitions the test DB
# creates, and far enough back that "previous week" also lands inside them.
WEEK_START = NOW - timedelta(days=10)
WEEK_END = WEEK_START + timedelta(days=7)
DASHBOARD = "https://streamintel.cc"


def _live(db: Session, channel, days_ago: float, **kwargs):
    return make_stream(
        db, channel, started_minutes_ago=int(days_ago * 24 * 60), **kwargs
    )


def test_week_with_no_lives_is_empty(db: Session) -> None:
    channel = make_channel(db)
    _live(db, channel, days_ago=1)  # outside the window

    digest = build_week(db, channel, WEEK_START, WEEK_END)

    assert digest.is_empty
    assert digest.lives == ()
    assert digest.totals.unique_chatters == 0


def test_only_lives_inside_the_window_are_counted(db: Session) -> None:
    channel = make_channel(db)
    inside = _live(db, channel, days_ago=9, title="dentro")
    _live(db, channel, days_ago=11, title="semana anterior")
    _live(db, channel, days_ago=2, title="depois")

    digest = build_week(db, channel, WEEK_START, WEEK_END)

    assert [live.stream_id for live in digest.lives] == [inside.id]


def test_unique_chatters_are_not_summed_across_lives(db: Session) -> None:
    """The same person on two lives is one chatter, not two."""
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9)
    second = _live(db, channel, days_ago=8)
    add_chat(db, first, count=3, author="mesma_pessoa")
    add_chat(db, second, count=4, author="mesma_pessoa")

    digest = build_week(db, channel, WEEK_START, WEEK_END)

    per_live = sum(live.metrics[RecordMetric.CHATTERS] for live in digest.lives)
    assert per_live == 2
    assert digest.totals.unique_chatters == 1


def test_totals_fold_per_metric(db: Session) -> None:
    """Messages sum, peak viewers take the highest, chat rate is recomputed."""
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9, duration_minutes=60)
    second = _live(db, channel, days_ago=8, duration_minutes=40)
    add_chat(db, first, count=10)
    add_chat(db, second, count=40)
    add_viewer_samples(db, first, [10, 30, 20])
    add_viewer_samples(db, second, [5, 8])

    totals = build_week(db, channel, WEEK_START, WEEK_END).totals.metrics

    assert totals[RecordMetric.MESSAGES] == 50
    assert totals[RecordMetric.PEAK_VIEWERS] == 30
    assert totals[RecordMetric.DURATION_MINUTES] == 100
    assert totals[RecordMetric.MESSAGES_PER_MIN] == 0.5
    assert RecordMetric.CHATTERS not in totals


def test_previous_week_is_loaded_for_comparison(db: Session) -> None:
    channel = make_channel(db)
    this_week = _live(db, channel, days_ago=9)
    last_week = _live(db, channel, days_ago=12)
    add_chat(db, this_week, count=30)
    add_chat(db, last_week, count=10)

    digest = build_week(db, channel, WEEK_START, WEEK_END)

    assert digest.previous is not None
    assert digest.previous.metrics[RecordMetric.MESSAGES] == 10
    assert "vs semana passada" in render_html(digest, DASHBOARD)


def test_previous_week_absent_when_there_was_none(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_chat(db, live, count=5)

    digest = build_week(db, channel, WEEK_START, WEEK_END)

    assert digest.previous is None
    assert "vs semana passada" not in render_html(digest, DASHBOARD)


def test_moments_rank_by_score_and_carry_their_explanation(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    weak = add_peak(db, live, offset_seconds=60, score=2.0)
    strong = add_peak(db, live, offset_seconds=3720, score=9.0)
    add_insight(
        db,
        live,
        insight_type=InsightType.PEAK_EXPLANATION,
        content="O chat explodiu com a jogada.",
        evidence={"peak_id": strong.id},
    )

    moments = build_week(db, channel, WEEK_START, WEEK_END).moments

    assert [m.score for m in moments] == [9.0, 2.0]
    assert moments[0].offset_label == "1h02m00s"
    assert moments[0].explanation == "O chat explodiu com a jogada."
    assert moments[1].explanation is None
    assert weak.id != strong.id


def test_top_topic_ranks_by_how_many_lives_mentioned_it(db: Session) -> None:
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9)
    second = _live(db, channel, days_ago=8)
    for live in (first, second):
        add_insight(
            db, live, insight_type=InsightType.TOPIC, content="Elden Ring\ndescrição"
        )
    add_insight(
        db, first, insight_type=InsightType.TOPIC, content="Setup novo\ndescrição"
    )

    topics = build_week(db, channel, WEEK_START, WEEK_END).topics

    assert topics[0] == ("Elden Ring", 2)
    assert ("Setup novo", 1) in topics


def test_records_hidden_until_the_channel_has_enough_history(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    db.add(
        StreamRecord(
            channel_id=channel.id,
            stream_id=live.id,
            metric=RecordMetric.MESSAGES.value,
            value=500.0,
            achieved_at=live.started_at,
        )
    )
    db.flush()

    assert build_week(db, channel, WEEK_START, WEEK_END).records == ()

    for day in range(4):
        _live(db, channel, days_ago=20 + day)

    records = build_week(db, channel, WEEK_START, WEEK_END).records
    assert records == ((RecordMetric.MESSAGES, 500.0),)


def test_kept_clips_of_the_week_are_listed(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    db.add_all(
        [
            TwitchClip(
                stream_id=live.id,
                channel_id=channel.id,
                clip_id="kept-1",
                edit_url="https://clips.twitch.tv/kept-1",
                title="A jogada",
                kept=True,
                created_at=live.started_at,
            ),
            TwitchClip(
                stream_id=live.id,
                channel_id=channel.id,
                clip_id="dropped-1",
                edit_url="https://clips.twitch.tv/dropped-1",
                kept=False,
                created_at=live.started_at,
            ),
        ]
    )
    db.flush()

    clips = build_week(db, channel, WEEK_START, WEEK_END).clips

    assert [clip.title for clip in clips] == ["A jogada"]


def test_render_uses_sql_numbers_and_escapes_text(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9, title="<script>alert(1)</script>")
    add_chat(db, live, count=7)
    add_event(db, live, event_type="channel.follow")
    add_insight(db, live, content="Resumo & tal.")

    html = render_html(build_week(db, channel, WEEK_START, WEEK_END), DASHBOARD)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "Resumo &amp; tal." in html
    assert "mensagens no chat: <strong>7</strong>" in html
    assert "seguidores ganhos: <strong>1</strong>" in html
    assert DASHBOARD in html


def test_last_week_bounds_is_the_previous_full_monday_week() -> None:
    zone = ZoneInfo("America/Sao_Paulo")
    # A Thursday; the last complete week is the Monday 10 days before.
    now = datetime(2026, 7, 23, 15, 0, tzinfo=UTC)

    start, end = last_week_bounds(now, zone)

    assert start.astimezone(zone).isoformat() == "2026-07-13T00:00:00-03:00"
    assert end - start == timedelta(days=7)
    assert start.astimezone(zone).weekday() == 0


def test_last_week_bounds_on_a_monday_excludes_the_running_week() -> None:
    zone = ZoneInfo("UTC")
    monday = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)

    start, end = last_week_bounds(monday, zone)

    assert start == datetime(2026, 7, 13, tzinfo=zone)
    assert end == datetime(2026, 7, 20, tzinfo=zone)
