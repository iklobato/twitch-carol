"""Community visualizations endpoint: chat share, word cloud, emotes,
presence heatmap and sentiment, computed in one pass over the messages."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import ceil

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.dashboard import _owned_stream
from apps.api.deps import CurrentChannel, DbSession
from core.models import ChatMessage, Stream
from core.text import (
    emote_names,
    meaningful_words,
    message_sentiment,
    strip_emotes,
    tokenize,
)

router = APIRouter(prefix="/api")

TOP_WORDS = 30
TOP_EMOTES = 15
SHARE_SLICES = 5
PRESENCE_ROWS = 10
PRESENCE_MAX_COLUMNS = 40
SENTIMENT_POSITIVE_THRESHOLD = 0.15
SENTIMENT_BUCKET_SECONDS = 30


class ShareSlice(BaseModel):
    login: str | None  # None = "outros"
    messages: int


class WordCount(BaseModel):
    word: str
    count: int


class EmoteCount(BaseModel):
    name: str
    count: int


class SentimentPoint(BaseModel):
    t: datetime
    score: float
    messages: int


class ChatterSentiment(BaseModel):
    login: str
    score: float


class PresenceRow(BaseModel):
    login: str
    cells: list[int]


class Presence(BaseModel):
    slots: list[datetime]
    rows: list[PresenceRow]


class CommunityOut(BaseModel):
    share: list[ShareSlice]
    words: list[WordCount]
    emotes: list[EmoteCount]
    sentiment_overall: float | None
    sentiment_timeline: list[SentimentPoint]
    sentiment_by_chatter: list[ChatterSentiment]
    presence: Presence


def _presence(
    stream: Stream,
    minute_counts: dict[tuple[str, int], int],
    top_logins: list[str],
    total_minutes: int,
) -> Presence:
    columns = min(PRESENCE_MAX_COLUMNS, max(total_minutes, 1))
    slot_minutes = ceil(max(total_minutes, 1) / columns)
    slots = [
        stream.started_at + timedelta(minutes=index * slot_minutes)
        for index in range(columns)
    ]
    rows = []
    for login in top_logins[:PRESENCE_ROWS]:
        cells = [0] * columns
        for (row_login, minute), count in minute_counts.items():
            if row_login == login:
                cells[min(minute // slot_minutes, columns - 1)] += count
        rows.append(PresenceRow(login=login, cells=cells))
    return Presence(slots=slots, rows=rows)


@router.get("/streams/{stream_id}/community")
def stream_community(
    stream_id: int, channel: CurrentChannel, db: DbSession
) -> CommunityOut:
    stream = _owned_stream(db, channel, stream_id)
    ended_at = stream.ended_at if stream.ended_at is not None else stream.started_at
    total_minutes = ceil(max((ended_at - stream.started_at).total_seconds() / 60, 1))

    per_login: Counter[str] = Counter()
    words: Counter[str] = Counter()
    emotes: Counter[str] = Counter()
    minute_counts: dict[tuple[str, int], int] = defaultdict(int)
    bucket_sentiment: dict[int, list[float]] = defaultdict(list)
    login_sentiment: dict[str, list[float]] = defaultdict(list)
    all_scores: list[float] = []

    rows = db.execute(
        select(
            ChatMessage.author_login,
            ChatMessage.sent_at,
            ChatMessage.text,
            ChatMessage.emotes,
        ).where(ChatMessage.stream_id == stream.id)
    ).yield_per(2000)

    for login, sent_at, text, message_emotes in rows:
        per_login[login] += 1
        offset_seconds = (sent_at - stream.started_at).total_seconds()
        minute = min(max(int(offset_seconds // 60), 0), total_minutes - 1)
        minute_counts[(login, minute)] += 1
        sentiment_bucket = max(int(offset_seconds // SENTIMENT_BUCKET_SECONDS), 0)

        for name in emote_names(text, message_emotes):
            emotes[name] += 1
        tokens = tokenize(strip_emotes(text, message_emotes))
        words.update(meaningful_words(text, message_emotes))
        score = message_sentiment(tokens)
        if score is not None:
            all_scores.append(score)
            bucket_sentiment[sentiment_bucket].append(score)
            login_sentiment[login].append(score)

    top = per_login.most_common(SHARE_SLICES)
    others = sum(per_login.values()) - sum(count for _, count in top)
    share = [ShareSlice(login=login, messages=count) for login, count in top]
    if others > 0:
        share.append(ShareSlice(login=None, messages=others))

    top_logins = [login for login, _ in per_login.most_common(PRESENCE_ROWS)]
    return CommunityOut(
        share=share,
        words=[WordCount(word=w, count=c) for w, c in words.most_common(TOP_WORDS)],
        emotes=[EmoteCount(name=n, count=c) for n, c in emotes.most_common(TOP_EMOTES)],
        sentiment_overall=(
            round(sum(all_scores) / len(all_scores), 2) if all_scores else None
        ),
        sentiment_timeline=[
            SentimentPoint(
                t=stream.started_at
                + timedelta(seconds=bucket * SENTIMENT_BUCKET_SECONDS),
                score=round(sum(scores) / len(scores), 2),
                messages=len(scores),
            )
            for bucket, scores in sorted(bucket_sentiment.items())
        ],
        sentiment_by_chatter=[
            ChatterSentiment(login=login, score=round(sum(scores) / len(scores), 2))
            for login, scores in sorted(
                login_sentiment.items(), key=lambda item: len(item[1]), reverse=True
            )[:SHARE_SLICES]
        ],
        presence=_presence(stream, minute_counts, top_logins, total_minutes),
    )
