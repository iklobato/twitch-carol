"""Weekly recap of a channel's lives, assembled from data already stored.

Read-only and LLM-free by design. Every number comes from SQL (the same
helpers the dashboard uses, never re-derived here) and every sentence was
already written and evidence-checked when each live was analyzed, so building
a week costs no model call and writes no row.

The week runs Monday 00:00 to Monday 00:00 in the channel's own timezone, and
a live belongs to the week it STARTED in (same rule the dashboard uses to put
a live on a calendar day).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from html import escape
from statistics import fmean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.i18n import format_number, t
from core.models import (
    Channel,
    ChatMessage,
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
from core.topics import recurring_topics

MOMENTS_LIMIT = 5
TOPICS_LIMIT = 5
CLIPS_LIMIT = 5

# Chat lives in monthly partitions on sent_at, so every chat query needs a
# sent_at range or postgres scans them all. The bound follows the lives instead
# of the week so a live crossing midnight into the next week still counts whole.
CHAT_TAIL_MARGIN = timedelta(hours=6)

# Shown in the email header block, in this order. The full fourteen metrics are
# too much for an email; these are the ones a streamer reads first.
HEADLINE_METRICS = (
    RecordMetric.MESSAGES,
    RecordMetric.PEAK_VIEWERS,
    RecordMetric.FOLLOWS,
    RecordMetric.DURATION_MINUTES,
)

# Summing per-live chatters double-counts anyone who showed up on two lives, so
# the week's figure comes from its own DISTINCT query.
NOT_SUMMABLE = frozenset({RecordMetric.CHATTERS})
# Recomputed from the week's totals; averaging per-live rates would weight a
# 20-minute live the same as a 6-hour one.
DERIVED = frozenset({RecordMetric.MESSAGES_PER_MIN})


def _total(values: Sequence[float]) -> float:
    return float(sum(values))


def _highest(values: Sequence[float]) -> float:
    return max(values)


def _mean(values: Sequence[float]) -> float:
    return fmean(values)


# How each metric folds across the week's lives. Summing is the default; these
# are the ones a sum would make nonsense of.
WEEK_FOLD: dict[RecordMetric, Callable[[Sequence[float]], float]] = {
    RecordMetric.PEAK_VIEWERS: _highest,
    RecordMetric.AVG_VIEWERS: _mean,
}


@dataclass(frozen=True)
class WeekLive:
    stream_id: int
    title: str | None
    category: str | None
    started_at: datetime
    summary: str | None
    metrics: Mapping[RecordMetric, float]


@dataclass(frozen=True)
class WeekMoment:
    """A chat peak, with the explanation the analysis already wrote for it."""

    stream_id: int
    stream_title: str | None
    offset_label: str
    score: float
    explanation: str | None


@dataclass(frozen=True)
class WeekClip:
    title: str | None
    url: str


@dataclass(frozen=True)
class WeekTotals:
    metrics: Mapping[RecordMetric, float]
    unique_chatters: int


@dataclass(frozen=True)
class WeekDigest:
    login: str
    display_name: str
    start: datetime
    end: datetime
    lives: tuple[WeekLive, ...]
    totals: WeekTotals
    previous: WeekTotals | None
    moments: tuple[WeekMoment, ...]
    topics: tuple[tuple[str, int], ...]
    records: tuple[tuple[RecordMetric, float], ...]
    clips: tuple[WeekClip, ...]
    # channels.language: the whole email is written in it.
    language: str

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


def _offset_label(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def _week_streams(
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


def _unique_chatters(db: Session, streams: list[Stream]) -> int:
    """Distinct chatters across the week. Cannot be summed from the per-live
    counts, which double-count anyone active on more than one live."""
    if not streams:
        return 0
    first = min(s.started_at for s in streams)
    last = max(s.ended_at or s.started_at for s in streams)
    return (
        db.scalar(
            select(func.count(func.distinct(ChatMessage.author_id)))
            .where(ChatMessage.stream_id.in_([s.id for s in streams]))
            .where(ChatMessage.sent_at >= first)
            .where(ChatMessage.sent_at < last + CHAT_TAIL_MARGIN)
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
        fold = WEEK_FOLD.get(metric, _total)
        folded[metric] = round(fold([live[metric] for live in per_live]), 2)
    minutes = folded[RecordMetric.DURATION_MINUTES]
    folded[RecordMetric.MESSAGES_PER_MIN] = (
        round(folded[RecordMetric.MESSAGES] / minutes, 2) if minutes > 0 else 0.0
    )
    return folded


def _totals(db: Session, streams: list[Stream]) -> WeekTotals:
    per_live = [compute_stream_metrics(db, stream) for stream in streams]
    return WeekTotals(
        metrics=_fold_metrics(per_live),
        unique_chatters=_unique_chatters(db, streams),
    )


def _summaries(db: Session, stream_ids: list[int]) -> dict[int, str]:
    rows = db.execute(
        select(Insight.stream_id, Insight.content)
        .where(Insight.stream_id.in_(stream_ids))
        .where(Insight.type == InsightType.SUMMARY)
    ).all()
    return {row[0]: row[1] for row in rows}


def _moments(db: Session, streams: list[Stream]) -> list[WeekMoment]:
    """The week's loudest chat peaks. Peak.score is already normalized against
    each live's own median, so it ranks fairly across lives of different sizes."""
    by_id = {stream.id: stream for stream in streams}
    peaks = db.scalars(
        select(Peak)
        .where(Peak.stream_id.in_(by_id))
        .order_by(Peak.score.desc())
        .limit(MOMENTS_LIMIT)
    ).all()
    if not peaks:
        return []
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
    moments = []
    for peak in peaks:
        stream = by_id[peak.stream_id]
        offset = int((peak.window_start - stream.started_at).total_seconds())
        moments.append(
            WeekMoment(
                stream_id=stream.id,
                stream_title=stream.title,
                offset_label=_offset_label(max(offset, 0)),
                score=round(peak.score, 1),
                explanation=text_by_peak.get(peak.id),
            )
        )
    return moments


def _records(
    db: Session, channel_id: int, start: datetime, end: datetime
) -> list[tuple[RecordMetric, float]]:
    """Records broken during the week. Hidden until the channel has enough
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
) -> list[WeekClip]:
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
    return [WeekClip(title=clip.title, url=clip.edit_url) for clip in rows]


def build_week(
    db: Session, channel: Channel, start: datetime, end: datetime
) -> WeekDigest:
    """Everything that happened for one channel in one week. No lives in the
    window means an empty digest and no further queries."""
    streams = _week_streams(db, channel.id, start, end)
    if not streams:
        return WeekDigest(
            login=channel.login,
            display_name=channel.display_name,
            start=start,
            end=end,
            lives=(),
            totals=WeekTotals(metrics={}, unique_chatters=0),
            previous=None,
            moments=(),
            topics=(),
            records=(),
            clips=(),
            language=channel.language,
        )

    stream_ids = [stream.id for stream in streams]
    summaries = _summaries(db, stream_ids)
    per_live = [compute_stream_metrics(db, stream) for stream in streams]
    previous_streams = _week_streams(db, channel.id, start - timedelta(days=7), start)
    return WeekDigest(
        login=channel.login,
        display_name=channel.display_name,
        start=start,
        end=end,
        lives=tuple(
            WeekLive(
                stream_id=stream.id,
                title=stream.title,
                category=stream.category,
                started_at=stream.started_at,
                summary=summaries.get(stream.id),
                metrics=metrics,
            )
            for stream, metrics in zip(streams, per_live, strict=True)
        ),
        totals=WeekTotals(
            metrics=_fold_metrics(per_live),
            unique_chatters=_unique_chatters(db, streams),
        ),
        previous=_totals(db, previous_streams) if previous_streams else None,
        moments=tuple(_moments(db, streams)),
        topics=tuple(recurring_topics(db, stream_ids, TOPICS_LIMIT)),
        records=tuple(_records(db, channel.id, start, end)),
        clips=tuple(_clips(db, channel.id, start, end)),
        language=channel.language,
    )


def delta_pct(current: float, previous: float) -> float | None:
    """None when there is no meaningful base to compare against."""
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _delta_label(digest: WeekDigest, metric: RecordMetric) -> str:
    if digest.previous is None:
        return ""
    delta = delta_pct(
        digest.totals.metrics[metric], digest.previous.metrics.get(metric, 0.0)
    )
    if delta is None:
        return ""
    return t(
        digest.language,
        "weekly.delta",
        sign="+" if delta >= 0 else "",
        pct=format_number(delta, digest.language, decimals=1),
    )


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px">{text}</p>'


def render_html(digest: WeekDigest, dashboard_url: str) -> str:
    """The recap as an email body. Deliberately plain (no tables, no images, no
    columns): a hand-typed look lands in the inbox, a newsletter look lands in
    spam. Same reasoning as the beta invite in ai-generated-messages/.

    Every number here is interpolated from SQL through format_value; no text
    that a model wrote is ever used to state a figure.
    """
    fmt = t(digest.language, "weekly.dateFormat")
    week = f"{digest.start:{fmt}} - {digest.end - timedelta(days=1):{fmt}}"
    parts = [
        _p(t(digest.language, "weekly.greeting", name=escape(digest.display_name))),
        _p(t(digest.language, "weekly.intro", week=week)),
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
        headline.append(
            t(
                digest.language,
                "weekly.metricLine",
                label=metric_label(metric, digest.language),
                value=format_value(
                    metric, digest.totals.metrics[metric], digest.language
                ),
                delta=_delta_label(digest, metric),
            )
        )
    headline.append(
        t(digest.language, "weekly.uniqueChatters")
        + f": <strong>{digest.totals.unique_chatters}</strong>"
    )
    parts.append(
        '<ul style="padding-left:20px;margin:0 0 14px">'
        + "".join(f"<li>{item}</li>" for item in headline)
        + "</ul>"
    )

    if digest.records:
        broken = ", ".join(
            f"{metric_label(metric, digest.language)} "
            f"({format_value(metric, value, digest.language)})"
            for metric, value in digest.records
        )
        parts.append(_p(t(digest.language, "weekly.records", broken=broken)))

    if digest.moments:
        parts.append(_p(t(digest.language, "weekly.moments")))
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
        parts.append(_p(t(digest.language, "weekly.clips")))
        parts.append(f'<ul style="padding-left:20px;margin:0 0 14px">{clip_items}</ul>')

    for live in digest.lives:
        if not live.summary:
            continue
        title = escape(live.title or t(digest.language, "weekly.untitledLive"))
        parts.append(
            _p(
                f"<strong>{live.started_at:{fmt}} - {title}</strong><br>{escape(live.summary)}"
            )
        )

    parts.append(
        _p(
            f'<a href="{escape(dashboard_url)}" style="color:#7b3fe4">'
            + t(digest.language, "weekly.cta")
            + "</a>"
        )
    )
    body = "".join(parts)
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        "sans-serif;font-size:15px;line-height:1.55;color:#1a1a1a;"
        f'max-width:560px">{body}</div>'
    )


def build_last_week(
    db: Session, channel: Channel, now: datetime | None = None
) -> WeekDigest:
    zone = channel_zone(channel)
    start, end = last_week_bounds(now or datetime.now(UTC), zone)
    return build_week(db, channel, start, end)
