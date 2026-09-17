"""Weekly/monthly recap digest: period boundaries, folded totals, revenue
sections and the rendered body."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from core.digest import (
    build_period,
    digest_subject,
    last_month_bounds,
    last_week_bounds,
    render_html,
    with_insights,
)
from core.models import DigestPeriod, InsightType, StreamRecord
from core.records import RecordMetric
from tests.factories import (
    add_chat,
    add_event,
    add_insight,
    add_peak,
    add_segment,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

NOW = datetime.now(UTC)
# A window in the recent past: inside the +/-31d chat partitions the test DB
# creates, and far enough back that "previous period" also lands inside them.
WEEK_START = NOW - timedelta(days=10)
WEEK_END = WEEK_START + timedelta(days=7)
DASHBOARD = "https://streamintel.cc"
UNSUBSCRIBE = "https://streamintel.cc/api/digest/unsubscribe?t=fake"


def _live(db: Session, channel, days_ago: float, **kwargs):
    return make_stream(
        db, channel, started_minutes_ago=int(days_ago * 24 * 60), **kwargs
    )


def _build_week(db: Session, channel):
    return build_period(db, channel, DigestPeriod.WEEKLY, WEEK_START, WEEK_END)


def test_period_with_no_lives_is_empty(db: Session) -> None:
    channel = make_channel(db)
    _live(db, channel, days_ago=1)  # outside the window

    digest = _build_week(db, channel)

    assert digest.is_empty
    assert digest.lives == ()
    assert digest.totals.unique_chatters == 0
    assert digest.topic_revenue == ()
    assert digest.content_revenue == ()


def test_only_lives_inside_the_window_are_counted(db: Session) -> None:
    channel = make_channel(db)
    inside = _live(db, channel, days_ago=9, title="dentro")
    _live(db, channel, days_ago=11, title="semana anterior")
    _live(db, channel, days_ago=2, title="depois")

    digest = _build_week(db, channel)

    assert [live.stream_id for live in digest.lives] == [inside.id]


def test_unique_chatters_are_not_summed_across_lives(db: Session) -> None:
    """The same person on two lives is one chatter, not two."""
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9)
    second = _live(db, channel, days_ago=8)
    add_chat(db, first, count=3, author="mesma_pessoa")
    add_chat(db, second, count=4, author="mesma_pessoa")

    digest = _build_week(db, channel)

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

    totals = _build_week(db, channel).totals.metrics

    assert totals[RecordMetric.MESSAGES] == 50
    assert totals[RecordMetric.PEAK_VIEWERS] == 30
    assert totals[RecordMetric.DURATION_MINUTES] == 100
    assert totals[RecordMetric.MESSAGES_PER_MIN] == 0.5
    assert RecordMetric.CHATTERS not in totals


def test_revenue_sums_across_lives_in_the_period(db: Session) -> None:
    """REVENUE_USD folds like any other summable metric: no separate plumbing
    needed, just the shared per-live metric already computed for records."""
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9)
    second = _live(db, channel, days_ago=8)
    add_event(db, first, "channel.cheer", offset_seconds=60, amount=500)
    add_event(db, second, "channel.cheer", offset_seconds=60, amount=300)

    digest = _build_week(db, channel)

    assert digest.totals.metrics[RecordMetric.REVENUE_USD] == 8.0


def test_previous_period_is_loaded_for_comparison(db: Session) -> None:
    channel = make_channel(db)
    channel.language = "pt"
    this_week = _live(db, channel, days_ago=9)
    last_week = _live(db, channel, days_ago=12)
    add_chat(db, this_week, count=30)
    add_chat(db, last_week, count=10)

    digest = _build_week(db, channel)

    assert digest.previous is not None
    assert digest.previous.metrics[RecordMetric.MESSAGES] == 10
    assert "vs semana passada" in render_html(digest, DASHBOARD, UNSUBSCRIBE)


def test_previous_period_absent_when_there_was_none(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_chat(db, live, count=5)

    digest = _build_week(db, channel)

    assert digest.previous is None
    assert "vs semana passada" not in render_html(digest, DASHBOARD, UNSUBSCRIBE)


def test_moments_rank_by_score_and_carry_their_explanation(db: Session) -> None:
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9)
    second = _live(db, channel, days_ago=8)
    weak = add_peak(db, first, offset_seconds=60, score=2.0)
    strong = add_peak(db, second, offset_seconds=3720, score=9.0)
    add_insight(
        db,
        second,
        insight_type=InsightType.PEAK_EXPLANATION,
        content="O chat explodiu com a jogada.",
        evidence={"peak_id": strong.id},
    )

    moments = _build_week(db, channel).moments

    assert [m.score for m in moments] == [9.0, 2.0]
    assert moments[0].offset_label == "1h02m00s"
    assert moments[0].explanation == "O chat explodiu com a jogada."
    assert moments[1].explanation is None
    assert weak.id != strong.id


def test_moments_keep_only_the_loudest_peak_per_live(db: Session) -> None:
    """A live's second, weaker peak would have made the old "top 5 peaks
    overall" list; it must not also show up now that each live contributes
    at most one moment."""
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_peak(db, live, offset_seconds=60, score=2.0)
    add_peak(db, live, offset_seconds=120, score=9.0)

    moments = _build_week(db, channel).moments

    assert len(moments) == 1
    assert moments[0].score == 9.0


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

    topics = _build_week(db, channel).topics

    assert topics[0] == ("Elden Ring", 2)
    assert ("Setup novo", 1) in topics


def test_topic_revenue_attributes_money_events_to_their_topic_window(
    db: Session,
) -> None:
    channel = make_channel(db)
    channel.language = "pt"
    live = _live(db, channel, days_ago=9)
    cheer = add_event(db, live, "channel.cheer", offset_seconds=310, amount=500)
    cheer.payload = {"user_login": "baleia"}
    segment = add_segment(db, live, 300, "falando de deploy", duration_seconds=60)
    add_insight(
        db,
        live,
        insight_type=InsightType.TOPIC,
        content="Deploy\nx",
        evidence={"segment_ids": [segment.id]},
    )
    add_chat(db, live, count=3, offset_seconds=320, spread_seconds=1)
    add_chat(db, live, count=2, offset_seconds=1000, spread_seconds=1)

    digest = _build_week(db, channel)

    assert digest.topic_revenue[0].name == "Deploy"
    assert digest.topic_revenue[0].estimated_usd == 5.0
    assert digest.topic_revenue[0].offset_label == "5m10s"
    assert digest.topic_revenue[0].stream_title == live.title
    assert digest.topic_revenue[0].chat_messages == 3
    html = render_html(digest, DASHBOARD, UNSUBSCRIBE)
    assert "Deploy" in html
    assert "US$ 5,00" in html
    assert "5m10s" in html


def test_content_revenue_groups_by_stream_category(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9, category="Just Chatting")
    cheer = add_event(db, live, "channel.cheer", offset_seconds=60, amount=1000)
    cheer.payload = {"user_login": "fan"}

    digest = _build_week(db, channel)

    assert digest.content_revenue[0].category == "Just Chatting"
    assert digest.content_revenue[0].estimated_usd == 10.0


def test_top_lives_by_revenue_ranks_the_highest_stream_first_with_its_moment(
    db: Session,
) -> None:
    channel = make_channel(db)
    quiet = _live(db, channel, days_ago=9)
    add_event(db, quiet, "channel.cheer", offset_seconds=60, amount=100)
    add_chat(db, quiet, count=50)

    top = _live(db, channel, days_ago=8)
    add_event(db, top, "channel.cheer", offset_seconds=60, amount=2000)
    add_chat(db, top, count=5)
    peak = add_peak(db, top, offset_seconds=90, score=7.0)
    add_insight(
        db,
        top,
        insight_type=InsightType.PEAK_EXPLANATION,
        content="Doou tudo.",
        evidence={"peak_id": peak.id},
    )

    digest = _build_week(db, channel)

    assert digest.top_lives_by_revenue[0].stream_id == top.id
    assert digest.top_lives_by_revenue[0].revenue_usd == 20.0
    assert digest.top_lives_by_revenue[0].messages == 5
    assert digest.top_lives_by_revenue[0].moment is not None
    assert digest.top_lives_by_revenue[0].moment.explanation == "Doou tudo."


def test_top_lives_by_revenue_is_empty_without_any_revenue(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_chat(db, live, count=5)

    digest = _build_week(db, channel)

    assert digest.top_lives_by_revenue == ()


def test_top_lives_by_messages_ranks_by_chat_volume_not_revenue(db: Session) -> None:
    channel = make_channel(db)
    loud = _live(db, channel, days_ago=9)
    add_chat(db, loud, count=20)

    rich = _live(db, channel, days_ago=8)
    add_chat(db, rich, count=2)
    cheer = add_event(db, rich, "channel.cheer", offset_seconds=60, amount=2000)
    cheer.payload = {"user_login": "baleia"}

    digest = _build_week(db, channel)

    assert digest.top_lives_by_messages[0].stream_id == loud.id
    assert digest.top_lives_by_messages[0].messages == 20
    assert digest.top_lives_by_revenue[0].stream_id == rich.id


def test_money_moments_lists_the_biggest_single_payments_first(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    small = add_event(db, live, "channel.cheer", offset_seconds=60, amount=100)
    small.payload = {"user_login": "shrimp"}
    big = add_event(db, live, "channel.cheer", offset_seconds=310, amount=2000)
    big.payload = {"user_login": "baleia"}

    digest = _build_week(db, channel)

    assert digest.money_moments[0].usd == 20.0
    assert digest.money_moments[0].contributor_login == "baleia"
    assert digest.money_moments[0].offset_label == "5m10s"
    assert digest.money_moments[1].usd == 1.0
    html = render_html(digest, DASHBOARD, UNSUBSCRIBE)
    assert "baleia" in html


def test_period_sentiment_is_none_below_the_minimum_sample(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_chat(db, live, count=5, text="great")

    digest = _build_week(db, channel)

    assert digest.sentiment is None


def test_period_sentiment_labels_the_average_once_theres_enough_signal(
    db: Session,
) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_chat(db, live, count=25, text="great")

    digest = _build_week(db, channel)

    assert digest.sentiment is not None
    assert digest.sentiment.label == "positive"
    assert digest.sentiment.score == 0.8
    assert digest.sentiment.messages == 25


def test_engaged_users_rank_by_streams_then_messages_and_carry_their_usd(
    db: Session,
) -> None:
    channel = make_channel(db)
    first = _live(db, channel, days_ago=9)
    second = _live(db, channel, days_ago=8)
    add_chat(db, first, count=3, author="fiel")
    add_chat(db, second, count=3, author="fiel")
    cheer = add_event(db, first, "channel.cheer", offset_seconds=60, amount=500)
    cheer.payload = {"user_login": "fiel"}
    add_chat(db, first, count=10, author="so_uma_live")

    engaged = _build_week(db, channel).engaged_users

    assert engaged[0].login == "fiel"
    assert engaged[0].streams_attended == 2
    assert engaged[0].messages == 6
    assert engaged[0].estimated_usd == 5.0
    only_one_live = next(u for u in engaged if u.login == "so_uma_live")
    assert only_one_live.streams_attended == 1
    assert only_one_live.estimated_usd == 0.0


def test_top_payers_rank_by_money_not_by_how_often_they_showed_up(db: Session) -> None:
    channel = make_channel(db)
    live = _live(db, channel, days_ago=9)
    add_chat(db, live, count=50, author="chatty_but_broke")
    cheer = add_event(db, live, "channel.cheer", offset_seconds=60, amount=2000)
    cheer.payload = {"user_login": "quiet_whale"}
    add_chat(db, live, count=1, author="quiet_whale")

    payers = _build_week(db, channel).top_payers

    assert payers[0].login == "quiet_whale"
    assert payers[0].estimated_usd == 20.0
    assert "chatty_but_broke" not in [p.login for p in payers]


def test_insights_are_absent_until_attached_then_render(db: Session) -> None:
    channel = make_channel(db)
    _live(db, channel, days_ago=9)

    digest = _build_week(db, channel)
    assert digest.insights == ()
    assert "weekly.insights" not in render_html(digest, DASHBOARD, UNSUBSCRIBE)

    with_ai = with_insights(digest, ["Receita cresceu 20% na categoria X."])
    assert with_ai.insights == ("Receita cresceu 20% na categoria X.",)
    assert "Receita cresceu 20% na categoria X." in render_html(
        with_ai, DASHBOARD, UNSUBSCRIBE
    )


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

    assert _build_week(db, channel).records == ()

    for day in range(4):
        _live(db, channel, days_ago=20 + day)

    records = _build_week(db, channel).records
    assert records == ((RecordMetric.MESSAGES, 500.0),)


def test_render_uses_sql_numbers_and_escapes_text(db: Session) -> None:
    channel = make_channel(db)
    channel.language = "pt"
    live = _live(db, channel, days_ago=9, title="<script>alert(1)</script>")
    add_chat(db, live, count=7)
    add_event(db, live, event_type="channel.follow")
    peak = add_peak(db, live, offset_seconds=60, score=5.0)
    add_insight(
        db,
        live,
        insight_type=InsightType.PEAK_EXPLANATION,
        content="Resumo & tal.",
        evidence={"peak_id": peak.id},
    )

    html = render_html(_build_week(db, channel), DASHBOARD, UNSUBSCRIBE)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "Resumo &amp; tal." in html
    assert "mensagens no chat: <strong>7</strong>" in html
    assert "seguidores ganhos: <strong>1</strong>" in html
    assert DASHBOARD in html
    assert UNSUBSCRIBE in html


def test_monthly_digest_uses_month_wording_for_the_delta(db: Session) -> None:
    """Events (not chat) so the test needs no monthly chat partition for
    whichever calendar month "a year ago" lands in."""
    channel = make_channel(db)
    channel.language = "pt"
    zone = ZoneInfo("UTC")
    now = datetime.now(UTC)
    start, end = last_month_bounds(now, zone)
    previous_start, _ = last_month_bounds(start, zone)

    this_month = make_stream(
        db,
        channel,
        started_minutes_ago=int(
            (now - (start + timedelta(days=1))).total_seconds() / 60
        ),
    )
    previous_month = make_stream(
        db,
        channel,
        started_minutes_ago=int(
            (now - (previous_start + timedelta(days=1))).total_seconds() / 60
        ),
    )
    add_event(db, this_month, "channel.follow", offset_seconds=60)
    add_event(db, previous_month, "channel.follow", offset_seconds=60)
    add_event(db, previous_month, "channel.follow", offset_seconds=90)

    digest = build_period(db, channel, DigestPeriod.MONTHLY, start, end)

    assert digest.previous is not None
    html = render_html(digest, DASHBOARD, UNSUBSCRIBE)
    assert "vs mês passado" in html
    assert "vs semana passada" not in html
    assert digest_subject(digest) == "Seu resumo mensal do StreamIntel"


def test_daily_revenue_buckets_by_local_calendar_day_and_only_renders_monthly(
    db: Session,
) -> None:
    channel = make_channel(db)
    zone = ZoneInfo("UTC")
    now = datetime.now(UTC)
    start, end = last_month_bounds(now, zone)
    live = make_stream(
        db,
        channel,
        started_minutes_ago=int(
            (now - (start + timedelta(days=2))).total_seconds() / 60
        ),
    )
    cheer = add_event(db, live, "channel.cheer", offset_seconds=60, amount=1000)
    cheer.payload = {"user_login": "baleia"}

    monthly = build_period(db, channel, DigestPeriod.MONTHLY, start, end)
    day = live.started_at.astimezone(zone).date()
    assert monthly.daily_revenue[day] == 10.0
    monthly_html = render_html(monthly, DASHBOARD, UNSUBSCRIBE)
    assert "display:table;width:100%" in monthly_html

    _live(db, channel, days_ago=9)
    weekly_html = render_html(_build_week(db, channel), DASHBOARD, UNSUBSCRIBE)
    assert "display:table;width:100%" not in weekly_html


def test_digest_subject_uses_weekly_wording_by_default(db: Session) -> None:
    channel = make_channel(db)
    digest = build_period(db, channel, DigestPeriod.WEEKLY, WEEK_START, WEEK_END)

    assert digest_subject(digest) == "Your weekly StreamIntel recap"


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


def test_last_month_bounds_is_the_previous_complete_calendar_month() -> None:
    zone = ZoneInfo("America/Sao_Paulo")
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    start, end = last_month_bounds(now, zone)

    assert start == datetime(2026, 8, 1, tzinfo=zone)
    assert end == datetime(2026, 9, 1, tzinfo=zone)


def test_last_month_bounds_on_the_first_excludes_the_running_month() -> None:
    zone = ZoneInfo("UTC")
    first_of_january = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    start, end = last_month_bounds(first_of_january, zone)

    assert start == datetime(2025, 12, 1, tzinfo=zone)
    assert end == datetime(2026, 1, 1, tzinfo=zone)
