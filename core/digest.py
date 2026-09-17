"""Weekly/monthly recap email: a channel's lives, revenue and a short LLM
insights section, assembled from data already stored.

Read-only except for the insights, which are attached separately (see
core.digest_insights) so this module stays LLM-free by design. Every number
comes from SQL (the same helpers the dashboard/finance pages use, never
re-derived here) and every summary sentence was already written and
evidence-checked when each live was analyzed.

A weekly period runs Monday 00:00 to Monday 00:00; a monthly period runs the
1st 00:00 to the 1st of the next month, both in the channel's own timezone. A
live belongs to the period it STARTED in, same rule the dashboard uses to put
a live on a calendar day.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from html import escape
from statistics import fmean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.channel import (
    ContentBucket,
    _content_revenue,
    _topic_revenue,
    _topic_windows_by_stream,
)
from core.db import month_bounds
from core.finance import MONEY_EVENT_TYPES, event_contributor, event_usd
from core.i18n import chat_language, format_number, t
from core.models import (
    Channel,
    ChatMessage,
    DigestPeriod,
    Event,
    Insight,
    InsightType,
    Peak,
    Stream,
    StreamRecord,
    StreamStatus,
    TwitchClip,
)
from core.records import (
    MIN_LIVES_FOR_RECORDS,
    RecordMetric,
    compute_stream_metrics,
    format_value,
    metric_label,
)
from core.text import message_sentiment, strip_emotes, tokenize
from core.topics import recurring_topics

MOMENTS_LIMIT = 5
TOPICS_LIMIT = 5
CLIPS_LIMIT = 5
ENGAGED_USERS_LIMIT = 5
# Fewer scored messages than this and a period's sentiment label is noise, not
# a signal: hide the section instead of stating a confident mood off 3 emotes.
MIN_SENTIMENT_MESSAGES = 20
# Same cutoff apps.api.community uses for its per-bucket positivity coloring,
# applied here to one average across the whole period instead of 30s buckets.
SENTIMENT_POSITIVE_THRESHOLD = 0.15

# Chat lives in monthly partitions on sent_at, so every chat query needs a
# sent_at range or postgres scans them all. The bound follows the lives instead
# of the period so a live crossing midnight into the next period still counts
# whole.
CHAT_TAIL_MARGIN = timedelta(hours=6)

# Shown in the email header block, in this order. The full fourteen metrics are
# too much for an email; these are the ones a streamer reads first.
HEADLINE_METRICS = (
    RecordMetric.MESSAGES,
    RecordMetric.PEAK_VIEWERS,
    RecordMetric.FOLLOWS,
    RecordMetric.REVENUE_USD,
    RecordMetric.DURATION_MINUTES,
)

# Summing per-live chatters double-counts anyone who showed up on two lives, so
# the period's figure comes from its own DISTINCT query.
NOT_SUMMABLE = frozenset({RecordMetric.CHATTERS})
# Recomputed from the period's totals; averaging per-live rates would weight a
# 20-minute live the same as a 6-hour one.
DERIVED = frozenset({RecordMetric.MESSAGES_PER_MIN})


def _total(values: Sequence[float]) -> float:
    return float(sum(values))


def _highest(values: Sequence[float]) -> float:
    return max(values)


def _mean(values: Sequence[float]) -> float:
    return fmean(values)


# How each metric folds across the period's lives. Summing is the default;
# these are the ones a sum would make nonsense of.
PERIOD_FOLD: dict[RecordMetric, Callable[[Sequence[float]], float]] = {
    RecordMetric.PEAK_VIEWERS: _highest,
    RecordMetric.AVG_VIEWERS: _mean,
}


@dataclass(frozen=True)
class DigestLive:
    stream_id: int
    title: str | None
    category: str | None
    started_at: datetime
    metrics: Mapping[RecordMetric, float]


@dataclass(frozen=True)
class DigestMoment:
    """A chat peak, with the explanation the analysis already wrote for it."""

    stream_id: int
    stream_title: str | None
    offset_label: str
    score: float
    explanation: str | None


@dataclass(frozen=True)
class DigestClip:
    title: str | None
    url: str


@dataclass(frozen=True)
class DigestTotals:
    metrics: Mapping[RecordMetric, float]
    unique_chatters: int


@dataclass(frozen=True)
class DigestTopicRevenue:
    """A monetizing topic plus, when one money event stands out inside its
    window, the moment that event happened."""

    name: str
    estimated_usd: float
    streams: int
    stream_title: str | None
    offset_label: str | None


@dataclass(frozen=True)
class DigestTopLive:
    """The period's single most valuable live: its own chat activity, its
    revenue, and its loudest moment if it had one."""

    stream_id: int
    title: str | None
    revenue_usd: float
    messages: int
    moment: DigestMoment | None


@dataclass(frozen=True)
class DigestSentiment:
    label: str  # "positive" | "neutral" | "negative"
    score: float
    messages: int


@dataclass(frozen=True)
class DigestEngagedUser:
    login: str
    messages: int
    streams_attended: int
    estimated_usd: float


@dataclass(frozen=True)
class Digest:
    period: DigestPeriod
    login: str
    display_name: str
    start: datetime
    end: datetime
    lives: tuple[DigestLive, ...]
    totals: DigestTotals
    previous: DigestTotals | None
    moments: tuple[DigestMoment, ...]
    topics: tuple[tuple[str, int], ...]
    records: tuple[tuple[RecordMetric, float], ...]
    clips: tuple[DigestClip, ...]
    topic_revenue: tuple[DigestTopicRevenue, ...]
    content_revenue: tuple[ContentBucket, ...]
    top_live: DigestTopLive | None
    sentiment: DigestSentiment | None
    engaged_users: tuple[DigestEngagedUser, ...]
    # channels.language: the whole email is written in it.
    language: str
    # Attached after build_period() by core.digest_insights, which is the only
    # part of this feature that calls an LLM. Empty until then.
    insights: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """No lives means there is nothing honest to say, so nothing is sent."""
        return not self.lives


def channel_zone(channel: Channel) -> ZoneInfo:
    try:
        return ZoneInfo(channel.timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def last_week_bounds(now: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """The last COMPLETE Monday-to-Monday week, in the channel's timezone."""
    today = now.astimezone(zone).date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    start = datetime.combine(last_monday, time.min, tzinfo=zone)
    return start, start + timedelta(days=7)


def last_month_bounds(now: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """The last COMPLETE calendar month, in the channel's timezone."""
    today = now.astimezone(zone).date()
    last_day_of_previous_month = today.replace(day=1) - timedelta(days=1)
    first, next_first = month_bounds(last_day_of_previous_month)
    return (
        datetime.combine(first, time.min, tzinfo=zone),
        datetime.combine(next_first, time.min, tzinfo=zone),
    )


def last_period_bounds(
    period: DigestPeriod, now: datetime, zone: ZoneInfo
) -> tuple[datetime, datetime]:
    if period == DigestPeriod.MONTHLY:
        return last_month_bounds(now, zone)
    return last_week_bounds(now, zone)


def _previous_period_bounds(
    period: DigestPeriod, start: datetime, zone: ZoneInfo
) -> tuple[datetime, datetime]:
    """The period immediately before `start`. Weeks are a fixed 7 days; months
    are not, so the monthly case goes through month_bounds instead of a fixed
    timedelta."""
    if period == DigestPeriod.WEEKLY:
        return start - timedelta(days=7), start
    previous_last_day = start.astimezone(zone).date() - timedelta(days=1)
    first, _ = month_bounds(previous_last_day)
    return datetime.combine(first, time.min, tzinfo=zone), start


def _offset_label(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def _period_streams(
    db: Session, channel_id: int, start: datetime, end: datetime
) -> list[Stream]:
    return list(
        db.scalars(
            select(Stream)
            .where(Stream.channel_id == channel_id)
            .where(Stream.status == StreamStatus.READY)
            .where(Stream.started_at >= start)
            .where(Stream.started_at < end)
            .order_by(Stream.started_at)
        ).all()
    )


def _chat_window(streams: list[Stream]) -> tuple[datetime, datetime]:
    """The [start, end) bound every ChatMessage query over a period needs:
    the table is partitioned by month on sent_at, so a query without this
    range makes postgres scan every partition instead of pruning to the
    relevant ones."""
    first = min(s.started_at for s in streams)
    last = max(s.ended_at or s.started_at for s in streams)
    return first, last + CHAT_TAIL_MARGIN


def _unique_chatters(db: Session, streams: list[Stream]) -> int:
    """Distinct chatters across the period. Cannot be summed from the per-live
    counts, which double-count anyone active on more than one live."""
    if not streams:
        return 0
    first, last = _chat_window(streams)
    return (
        db.scalar(
            select(func.count(func.distinct(ChatMessage.author_id)))
            .where(ChatMessage.stream_id.in_([s.id for s in streams]))
            .where(ChatMessage.sent_at >= first)
            .where(ChatMessage.sent_at < last)
        )
        or 0
    )


def _fold_metrics(
    per_live: Sequence[Mapping[RecordMetric, float]],
) -> dict[RecordMetric, float]:
    folded: dict[RecordMetric, float] = {}
    for metric in RecordMetric:
        if metric in NOT_SUMMABLE or metric in DERIVED:
            continue
        fold = PERIOD_FOLD.get(metric, _total)
        folded[metric] = round(fold([live[metric] for live in per_live]), 2)
    minutes = folded[RecordMetric.DURATION_MINUTES]
    folded[RecordMetric.MESSAGES_PER_MIN] = (
        round(folded[RecordMetric.MESSAGES] / minutes, 2) if minutes > 0 else 0.0
    )
    return folded


def _totals(db: Session, streams: list[Stream]) -> DigestTotals:
    per_live = [compute_stream_metrics(db, stream) for stream in streams]
    return DigestTotals(
        metrics=_fold_metrics(per_live),
        unique_chatters=_unique_chatters(db, streams),
    )


def _best_moment_per_live(
    db: Session, streams: list[Stream]
) -> dict[int, DigestMoment]:
    """Each live's single loudest chat peak, keyed by stream_id. Peak.score is
    already normalized against each live's own median, so it ranks fairly
    across lives of different sizes. Callers cap or pick from this map; it
    is not capped here so a live can be the top_live highlight even when its
    peak doesn't make the "best moments" list's own limit."""
    by_id = {stream.id: stream for stream in streams}
    if not by_id:
        return {}
    peaks = db.scalars(
        select(Peak)
        .where(Peak.stream_id.in_(by_id))
        .order_by(Peak.stream_id, Peak.score.desc())
    ).all()
    best_peak: dict[int, Peak] = {}
    for peak in peaks:
        best_peak.setdefault(peak.stream_id, peak)
    if not best_peak:
        return {}
    explanations = db.scalars(
        select(Insight)
        .where(Insight.stream_id.in_(by_id))
        .where(Insight.type == InsightType.PEAK_EXPLANATION)
    ).all()
    # The peak an explanation belongs to is inside its JSONB evidence, not a FK.
    text_by_peak = {
        insight.evidence.get("peak_id"): insight.content
        for insight in explanations
        if insight.evidence.get("peak_id")
    }
    moments: dict[int, DigestMoment] = {}
    for stream_id, peak in best_peak.items():
        stream = by_id[stream_id]
        offset = int((peak.window_start - stream.started_at).total_seconds())
        moments[stream_id] = DigestMoment(
            stream_id=stream.id,
            stream_title=stream.title,
            offset_label=_offset_label(max(offset, 0)),
            score=round(peak.score, 1),
            explanation=text_by_peak.get(peak.id),
        )
    return moments


def _topic_moments(
    events: Sequence[Event],
    windows: dict[int, list[tuple[str, datetime, datetime]]],
    streams_by_id: dict[int, Stream],
) -> dict[str, tuple[str | None, str]]:
    """For each topic name, the stream title and offset label of its single
    highest-value money event, using the same window attribution _topic_revenue
    (apps.api.channel) uses to sum that topic's revenue."""
    best_event: dict[str, Event] = {}
    best_stream_id: dict[str, int] = {}
    for event in events:
        for name, start, end in windows.get(event.stream_id, []):
            if not (start <= event.occurred_at < end):
                continue
            current = best_event.get(name)
            if current is None or event_usd(event) > event_usd(current):
                best_event[name] = event
                best_stream_id[name] = event.stream_id
    moments: dict[str, tuple[str | None, str]] = {}
    for name, event in best_event.items():
        stream = streams_by_id.get(best_stream_id[name])
        if stream is None:
            continue
        offset = int((event.occurred_at - stream.started_at).total_seconds())
        moments[name] = (stream.title, _offset_label(max(offset, 0)))
    return moments


def _top_live(
    streams: list[Stream],
    per_live: Sequence[Mapping[RecordMetric, float]],
    moments_by_stream: dict[int, DigestMoment],
) -> DigestTopLive | None:
    """The period's single most valuable live. None when nobody monetized
    this period, since there is nothing to highlight."""
    stream, metrics = max(
        zip(streams, per_live, strict=True),
        key=lambda pair: pair[1][RecordMetric.REVENUE_USD],
    )
    if metrics[RecordMetric.REVENUE_USD] <= 0:
        return None
    return DigestTopLive(
        stream_id=stream.id,
        title=stream.title,
        revenue_usd=metrics[RecordMetric.REVENUE_USD],
        messages=int(metrics[RecordMetric.MESSAGES]),
        moment=moments_by_stream.get(stream.id),
    )


def _sentiment_label(score: float) -> str:
    if score >= SENTIMENT_POSITIVE_THRESHOLD:
        return "positive"
    if score <= -SENTIMENT_POSITIVE_THRESHOLD:
        return "negative"
    return "neutral"


def _period_sentiment(
    db: Session, streams: list[Stream], language: str
) -> DigestSentiment | None:
    """Average chat sentiment across the whole period, same lexicon heuristic
    core.text.message_sentiment applies per-stream in the live community view.
    Hidden under MIN_SENTIMENT_MESSAGES scored messages, so a quiet period
    doesn't get a confident-looking label off a handful of reactions."""
    if not streams:
        return None
    first, last = _chat_window(streams)
    rows = db.execute(
        select(ChatMessage.text, ChatMessage.emotes)
        .where(ChatMessage.stream_id.in_([s.id for s in streams]))
        .where(ChatMessage.sent_at >= first)
        .where(ChatMessage.sent_at < last)
    ).yield_per(2000)
    scores = [
        score
        for text, emotes in rows
        if (score := message_sentiment(tokenize(strip_emotes(text, emotes)), language))
        is not None
    ]
    if len(scores) < MIN_SENTIMENT_MESSAGES:
        return None
    average = round(sum(scores) / len(scores), 2)
    return DigestSentiment(
        label=_sentiment_label(average), score=average, messages=len(scores)
    )


def _engaged_users(
    db: Session, streams: list[Stream], money_events: Sequence[Event]
) -> list[DigestEngagedUser]:
    """The period's most engaged chatters, ordered the way _loyal_chatters
    (apps.api.channel) ranks loyalty all-time (streams attended, then message
    volume), alongside how much each one monetized in the same window."""
    if not streams:
        return []
    first, last = _chat_window(streams)
    rows = db.execute(
        select(
            ChatMessage.author_login,
            func.count(func.distinct(ChatMessage.stream_id)),
            func.count(),
        )
        .where(ChatMessage.stream_id.in_([s.id for s in streams]))
        .where(ChatMessage.sent_at >= first)
        .where(ChatMessage.sent_at < last)
        .group_by(ChatMessage.author_login)
        .order_by(
            func.count(func.distinct(ChatMessage.stream_id)).desc(),
            func.count().desc(),
        )
        .limit(ENGAGED_USERS_LIMIT)
    ).all()
    usd_by_login: dict[str, float] = defaultdict(float)
    for event in money_events:
        login = event_contributor(event)
        if login:
            usd_by_login[login] += event_usd(event)
    return [
        DigestEngagedUser(
            login=login,
            streams_attended=streams_attended,
            messages=messages,
            estimated_usd=round(usd_by_login.get(login, 0.0), 2),
        )
        for login, streams_attended, messages in rows
    ]


def _records(
    db: Session, channel_id: int, start: datetime, end: datetime
) -> list[tuple[RecordMetric, float]]:
    """Records broken during the period. Hidden until the channel has enough
    history for a record to mean anything."""
    ready_lives = db.scalar(
        select(func.count())
        .select_from(Stream)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.READY)
    )
    if (ready_lives or 0) < MIN_LIVES_FOR_RECORDS:
        return []
    rows = db.execute(
        select(StreamRecord.metric, func.max(StreamRecord.value))
        .where(StreamRecord.channel_id == channel_id)
        .where(StreamRecord.achieved_at >= start)
        .where(StreamRecord.achieved_at < end)
        .group_by(StreamRecord.metric)
    ).all()
    best = {row[0]: row[1] for row in rows}
    return [
        (metric, best[metric.value]) for metric in RecordMetric if metric.value in best
    ]


def _clips(
    db: Session, channel_id: int, start: datetime, end: datetime
) -> list[DigestClip]:
    """Clips the streamer chose to keep: the strongest signal of a moment they
    liked themselves."""
    rows = db.scalars(
        select(TwitchClip)
        .where(TwitchClip.channel_id == channel_id)
        .where(TwitchClip.kept.is_(True))
        .where(TwitchClip.created_at >= start)
        .where(TwitchClip.created_at < end)
        .order_by(TwitchClip.created_at)
        .limit(CLIPS_LIMIT)
    ).all()
    return [DigestClip(title=clip.title, url=clip.edit_url) for clip in rows]


def _money_events(db: Session, stream_ids: list[int]) -> list[Event]:
    if not stream_ids:
        return []
    return list(
        db.scalars(
            select(Event)
            .where(Event.stream_id.in_(stream_ids))
            .where(Event.type.in_(MONEY_EVENT_TYPES))
        ).all()
    )


def build_period(
    db: Session, channel: Channel, period: DigestPeriod, start: datetime, end: datetime
) -> Digest:
    """Everything that happened for one channel in one period. No lives in the
    window means an empty digest and no further queries."""
    streams = _period_streams(db, channel.id, start, end)
    if not streams:
        return Digest(
            period=period,
            login=channel.login,
            display_name=channel.display_name,
            start=start,
            end=end,
            lives=(),
            totals=DigestTotals(metrics={}, unique_chatters=0),
            previous=None,
            moments=(),
            topics=(),
            records=(),
            clips=(),
            topic_revenue=(),
            content_revenue=(),
            top_live=None,
            sentiment=None,
            engaged_users=(),
            language=channel.language,
        )

    stream_ids = [stream.id for stream in streams]
    per_live = [compute_stream_metrics(db, stream) for stream in streams]
    zone = channel_zone(channel)
    previous_start, previous_end = _previous_period_bounds(period, start, zone)
    previous_streams = _period_streams(db, channel.id, previous_start, previous_end)

    streams_by_id = {stream.id: stream for stream in streams}
    windows = _topic_windows_by_stream(db, stream_ids)
    money_events = _money_events(db, stream_ids)
    moments_by_stream = _best_moment_per_live(db, streams)
    top_moments = sorted(
        moments_by_stream.values(), key=lambda moment: moment.score, reverse=True
    )[:MOMENTS_LIMIT]
    topic_moments = _topic_moments(money_events, windows, streams_by_id)

    return Digest(
        period=period,
        login=channel.login,
        display_name=channel.display_name,
        start=start,
        end=end,
        lives=tuple(
            DigestLive(
                stream_id=stream.id,
                title=stream.title,
                category=stream.category,
                started_at=stream.started_at,
                metrics=metrics,
            )
            for stream, metrics in zip(streams, per_live, strict=True)
        ),
        totals=DigestTotals(
            metrics=_fold_metrics(per_live),
            unique_chatters=_unique_chatters(db, streams),
        ),
        previous=_totals(db, previous_streams) if previous_streams else None,
        moments=tuple(top_moments),
        topics=tuple(recurring_topics(db, stream_ids, TOPICS_LIMIT)),
        records=tuple(_records(db, channel.id, start, end)),
        clips=tuple(_clips(db, channel.id, start, end)),
        topic_revenue=tuple(
            DigestTopicRevenue(
                name=topic.name,
                estimated_usd=topic.estimated_usd,
                streams=topic.streams,
                stream_title=topic_moments.get(topic.name, (None, None))[0],
                offset_label=topic_moments.get(topic.name, (None, None))[1],
            )
            for topic in _topic_revenue(money_events, windows)
        ),
        content_revenue=tuple(_content_revenue(db, channel.id, stream_ids)),
        top_live=_top_live(streams, per_live, moments_by_stream),
        sentiment=_period_sentiment(
            db, streams, chat_language(channel.spoken_language, channel.language)
        ),
        engaged_users=tuple(_engaged_users(db, streams, money_events)),
        language=channel.language,
    )


def with_insights(digest: Digest, insights: Sequence[str]) -> Digest:
    """Attach the LLM insights generated separately (core.digest_insights)."""
    return replace(digest, insights=tuple(insights))


def delta_pct(current: float, previous: float) -> float | None:
    """None when there is no meaningful base to compare against."""
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _delta_label(digest: Digest, metric: RecordMetric) -> str:
    if digest.previous is None:
        return ""
    delta = delta_pct(
        digest.totals.metrics[metric], digest.previous.metrics.get(metric, 0.0)
    )
    if delta is None:
        return ""
    key = "monthly.delta" if digest.period == DigestPeriod.MONTHLY else "weekly.delta"
    text = t(
        digest.language,
        key,
        sign="+" if delta >= 0 else "",
        pct=format_number(delta, digest.language, decimals=1),
    )
    color, arrow = ("#0a8a3f", "▲") if delta >= 0 else ("#c0392b", "▼")
    return f'<span style="color:{color};font-weight:600">{arrow}</span>{text}'


# Emoji, not an image: every mail client renders these inline for free, no
# attachment and no extra spam signal.
_METRIC_ICON: dict[RecordMetric, str] = {
    RecordMetric.MESSAGES: "\U0001f4ac",
    RecordMetric.PEAK_VIEWERS: "\U0001f465",
    RecordMetric.FOLLOWS: "❤️",
    RecordMetric.REVENUE_USD: "\U0001f4b0",
    RecordMetric.DURATION_MINUTES: "⏱️",
}


def _comparison_bar(current: float, previous: float) -> str:
    """A two-line CSS bar (no image) showing this period against the last
    one, right under a headline metric. Skipped when there is nothing to
    compare against, same condition as _delta_label."""
    if previous <= 0:
        return ""
    top = max(current, previous, 1.0)
    current_pct = round(min(current, top) / top * 100)
    previous_pct = round(min(previous, top) / top * 100)
    return (
        '<div style="margin-top:5px">'
        f'<div style="background:#e4defa;border-radius:3px;height:5px;'
        f'width:{previous_pct}%;margin-bottom:3px"></div>'
        f'<div style="background:#7b3fe4;border-radius:3px;height:5px;'
        f'width:{current_pct}%"></div></div>'
    )


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px">{text}</p>'


def _section_title(text: str) -> str:
    return (
        '<p style="margin:22px 0 10px;padding-top:16px;border-top:1px solid #eee;'
        f'font-size:13px;letter-spacing:.02em;color:#7b3fe4">{text}</p>'
    )


def _moment_suffix(
    digest: Digest, stream_title: str | None, offset_label: str | None
) -> str:
    """The "<strong>12m03s</strong> in "Title"" fragment shared by every
    section that points at one specific moment."""
    if not offset_label:
        return ""
    suffix = f" (<strong>{offset_label}</strong>"
    if stream_title:
        suffix += t(digest.language, "weekly.momentIn", title=escape(stream_title))
    return suffix + ")"


def _topic_revenue_line(digest: Digest, topic: DigestTopicRevenue) -> str:
    usd = format_value(RecordMetric.REVENUE_USD, topic.estimated_usd, digest.language)
    line = t(
        digest.language,
        "weekly.topicRevenueLine",
        name=escape(topic.name),
        usd=usd,
        streams=topic.streams,
    )
    return f"<li>{line}{_moment_suffix(digest, topic.stream_title, topic.offset_label)}</li>"


def _top_live_line(digest: Digest, top_live: DigestTopLive) -> str:
    title = escape(top_live.title or t(digest.language, "weekly.untitledLive"))
    line = t(
        digest.language,
        "weekly.topLiveLine",
        title=title,
        usd=format_value(
            RecordMetric.REVENUE_USD, top_live.revenue_usd, digest.language
        ),
        messages=top_live.messages,
    )
    moment = top_live.moment
    suffix = (
        _moment_suffix(digest, moment.stream_title, moment.offset_label)
        if moment
        else ""
    )
    return f"<li>{line}{suffix}</li>"


_SENTIMENT_LABEL_KEY = {
    "positive": "weekly.sentimentPositive",
    "neutral": "weekly.sentimentNeutral",
    "negative": "weekly.sentimentNegative",
}


def _sentiment_line(digest: Digest, sentiment: DigestSentiment) -> str:
    label = t(digest.language, _SENTIMENT_LABEL_KEY[sentiment.label])
    line = t(
        digest.language,
        "weekly.sentimentLine",
        label=label,
        messages=sentiment.messages,
    )
    return f"<li>{line}</li>"


def _engaged_user_line(digest: Digest, user: DigestEngagedUser) -> str:
    line = t(
        digest.language,
        "weekly.engagedUserLine",
        login=escape(user.login),
        messages=user.messages,
        streams=user.streams_attended,
        usd=format_value(RecordMetric.REVENUE_USD, user.estimated_usd, digest.language),
    )
    return f"<li>{line}</li>"


def digest_subject(digest: Digest) -> str:
    key = (
        "monthly.subject" if digest.period == DigestPeriod.MONTHLY else "weekly.subject"
    )
    return t(digest.language, key)


def render_html(digest: Digest, dashboard_url: str, unsubscribe_url: str) -> str:
    """The recap as an email body. Lightly branded, but still no images, no
    tables, no tracking pixel and no external fonts/CSS: those are what
    actually land a newsletter in spam, not a splash of color on a <div>.

    Every number here is interpolated from SQL through format_value; no text
    that a model wrote is ever used to state a figure. The insights section is
    the one exception, and it only ever states a fact it can cite (see
    core.digest_insights), not a bare number of its own choosing.
    """
    fmt = t(digest.language, "weekly.dateFormat")
    window = f"{digest.start:{fmt}} - {digest.end - timedelta(days=1):{fmt}}"
    parts = [
        f'<p style="margin:0 0 6px;font-size:19px;font-weight:700">'
        f'{t(digest.language, "weekly.greeting", name=escape(digest.display_name))}</p>',
        _p(t(digest.language, "weekly.intro", week=window)),
    ]

    lives = len(digest.lives)
    live_count = t(
        digest.language,
        "weekly.lives" if lives == 1 else "weekly.livesPlural",
        n=lives,
    )
    # "<label>: <value>" is the one phrasing that reads right for every metric
    # label ("peak viewers: 320", not "320 of peak viewers").
    headline = [f"<strong>{live_count}</strong>"]
    for metric in HEADLINE_METRICS:
        current = digest.totals.metrics[metric]
        previous = digest.previous.metrics.get(metric, 0.0) if digest.previous else 0.0
        line = t(
            digest.language,
            "weekly.metricLine",
            label=f"{_METRIC_ICON.get(metric, '')} {metric_label(metric, digest.language)}",
            value=format_value(metric, current, digest.language),
            delta=_delta_label(digest, metric),
        )
        headline.append(line + _comparison_bar(current, previous))
    headline.append(
        t(digest.language, "weekly.uniqueChatters")
        + f": <strong>{digest.totals.unique_chatters}</strong>"
    )
    parts.append(
        '<div style="background:#f7f5fc;border-radius:10px;padding:14px 18px;margin:6px 0 16px">'
        '<ul style="padding-left:18px;margin:0;list-style:none">'
        + "".join(f'<li style="margin-bottom:6px">{item}</li>' for item in headline)
        + "</ul></div>"
    )

    if digest.records:
        broken = ", ".join(
            f"{metric_label(metric, digest.language)} "
            f"({format_value(metric, value, digest.language)})"
            for metric, value in digest.records
        )
        parts.append(_p(t(digest.language, "weekly.records", broken=broken)))

    if digest.topic_revenue:
        parts.append(_section_title(t(digest.language, "weekly.topicRevenue")))
        topic_items = "".join(
            _topic_revenue_line(digest, topic) for topic in digest.topic_revenue
        )
        parts.append(
            f'<ul style="padding-left:20px;margin:0 0 14px">{topic_items}</ul>'
        )

    if digest.top_live:
        parts.append(_section_title(t(digest.language, "weekly.topLive")))
        parts.append(
            f'<ul style="padding-left:20px;margin:0 0 14px">'
            f"{_top_live_line(digest, digest.top_live)}</ul>"
        )

    if digest.moments:
        parts.append(_section_title(t(digest.language, "weekly.moments")))
        items = []
        for moment in digest.moments:
            line = f"<strong>{moment.offset_label}</strong>"
            if moment.stream_title:
                line += t(
                    digest.language,
                    "weekly.momentIn",
                    title=escape(moment.stream_title),
                )
            if moment.explanation:
                line += f": {escape(moment.explanation)}"
            items.append(f'<li style="margin-bottom:8px">{line}</li>')
        parts.append(
            f'<ul style="padding-left:20px;margin:0 0 14px">{"".join(items)}</ul>'
        )

    if digest.sentiment:
        parts.append(_section_title(t(digest.language, "weekly.sentiment")))
        parts.append(
            f'<ul style="padding-left:20px;margin:0 0 14px">'
            f"{_sentiment_line(digest, digest.sentiment)}</ul>"
        )

    if digest.engaged_users:
        parts.append(_section_title(t(digest.language, "weekly.engagedUsers")))
        user_items = "".join(
            _engaged_user_line(digest, user) for user in digest.engaged_users
        )
        parts.append(f'<ul style="padding-left:20px;margin:0 0 14px">{user_items}</ul>')

    if digest.insights:
        parts.append(_section_title(t(digest.language, "weekly.insights")))
        insight_items = "".join(
            f"<li>{escape(insight)}</li>" for insight in digest.insights
        )
        parts.append(
            f'<ul style="padding-left:20px;margin:0 0 14px">{insight_items}</ul>'
        )

    if digest.topics:
        top = digest.topics[0]
        parts.append(
            _p(
                t(
                    digest.language,
                    "weekly.topTopic",
                    name=escape(top[0]),
                    count=top[1],
                    total=live_count,
                )
            )
        )
        if len(digest.topics) > 1:
            rest = ", ".join(escape(name) for name, _ in digest.topics[1:])
            parts.append(_p(t(digest.language, "weekly.otherTopics", rest=rest)))

    if digest.clips:
        untitled = t(digest.language, "weekly.untitledClip")
        clip_items = "".join(
            f'<li><a href="{escape(clip.url)}" style="color:#7b3fe4">'
            f"{escape(clip.title or untitled)}</a></li>"
            for clip in digest.clips
        )
        parts.append(_section_title(t(digest.language, "weekly.clips")))
        parts.append(f'<ul style="padding-left:20px;margin:0 0 14px">{clip_items}</ul>')

    parts.append(
        f'<p style="margin:26px 0 18px;text-align:center">'
        f'<a href="{escape(dashboard_url)}" style="display:inline-block;'
        "background:#7b3fe4;color:#fff;padding:12px 26px;border-radius:6px;"
        f'text-decoration:none;font-weight:600;font-size:14px">'
        + t(digest.language, "weekly.cta")
        + "</a></p>"
    )
    parts.append(
        '<p style="margin:0;padding-top:14px;border-top:1px solid #eee;'
        f'font-size:12px;color:#999"><a href="{escape(unsubscribe_url)}" '
        'style="color:#999;text-decoration:underline">'
        + t(digest.language, "weekly.unsubscribe")
        + "</a></p>"
    )
    body = "".join(parts)
    header = (
        '<div style="background:#7b3fe4;padding:16px 28px;border-radius:12px 12px 0 0">'
        '<span style="color:#fff;font-size:16px;font-weight:700;'
        'letter-spacing:.02em">StreamIntel</span></div>'
    )
    return (
        '<div style="background:#f4f4f7;padding:24px 12px;font-family:'
        '-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        f'<div style="max-width:560px;margin:0 auto">{header}'
        '<div style="background:#fff;padding:26px 28px;border-radius:0 0 12px 12px;'
        f'font-size:15px;line-height:1.55;color:#1a1a1a">{body}</div>'
        "</div></div>"
    )


def build_last_period(
    db: Session, channel: Channel, period: DigestPeriod, now: datetime | None = None
) -> Digest:
    zone = channel_zone(channel)
    start, end = last_period_bounds(period, now or datetime.now(UTC), zone)
    return build_period(db, channel, period, start, end)
