"""Community visualizations endpoint: chat share, word cloud, emotes,
presence heatmap and sentiment, computed in one pass over the messages.

Sentiment is a transparent BR-Twitch lexicon heuristic (slang, laughter,
emojis) scored per message and averaged per minute/chatter.
"""

# ponytail: lexicon sentiment has a known ceiling (no sarcasm/negation);
# upgrade path is sampling messages through the local LLM at analyze time.

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import ceil

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.dashboard import _owned_stream
from apps.api.deps import CurrentChannel, DbSession
from core.models import ChatMessage, Stream

router = APIRouter(prefix="/api")

TOP_WORDS = 30
TOP_EMOTES = 15
SHARE_SLICES = 5
PRESENCE_ROWS = 10
PRESENCE_MAX_COLUMNS = 40
MIN_WORD_LENGTH = 3
SENTIMENT_POSITIVE_THRESHOLD = 0.15

STOPWORDS = frozenset(
    """a o e é de da do das dos em no na nos nas um uma uns umas que com para pra pro
    por se não nao sim mais menos muito muita muitos muitas pouco ja já foi ser ter
    tem tinha vai vou como quando onde quem qual quais isso isto aquilo ele ela eles
    elas você voce vc vcs eu tu nós nos meu minha seu sua teu tua dele dela deles
    ao aos à às até entre sobre sem sob mas ou nem porque porquê pois então entao
    lá la aqui ali agora hoje ontem amanhã amanha depois antes sempre nunca também
    tambem só so ainda outra outro outros outras esse essa esses essas este esta
    estes estas era são sao está esta estão estao estou tô to tava fazer faz fez
    dia gente cara mano tipo coisa pelo pela pelos pelas desse dessa deste desta
    disso nisso nesse nessa neste nesta num numa hein né ne aí ai eh tá ta pode
    the is are was and you for this that with
    """.split()
)

# score in [-1, 1]; BR Twitch chat vocabulary
LEXICON: dict[str, float] = {
    "bom": 0.5,
    "boa": 0.5,
    "ótimo": 1.0,
    "otimo": 1.0,
    "incrível": 1.0,
    "incrivel": 1.0,
    "top": 0.7,
    "brabo": 0.8,
    "braba": 0.8,
    "foda": 0.8,
    "lindo": 0.7,
    "linda": 0.7,
    "amei": 1.0,
    "amo": 0.9,
    "adoro": 0.8,
    "perfeito": 1.0,
    "perfeita": 1.0,
    "gg": 0.6,
    "pog": 0.8,
    "poggers": 0.8,
    "hype": 0.7,
    "demais": 0.5,
    "massa": 0.7,
    "maneiro": 0.6,
    "legal": 0.5,
    "show": 0.6,
    "aula": 0.6,
    "genial": 0.9,
    "obrigado": 0.6,
    "obrigada": 0.6,
    "valeu": 0.5,
    "parabéns": 0.8,
    "parabens": 0.8,
    "melhor": 0.6,
    "vitória": 0.8,
    "vitoria": 0.8,
    "ganhou": 0.6,
    "clipa": 0.6,
    "absurda": 0.6,
    "absurdo": 0.6,
    "ruim": -0.6,
    "péssimo": -1.0,
    "pessimo": -1.0,
    "horrível": -1.0,
    "horrivel": -1.0,
    "lixo": -1.0,
    "chato": -0.6,
    "chata": -0.6,
    "triste": -0.6,
    "odeio": -1.0,
    "flop": -0.7,
    "cringe": -0.6,
    "bosta": -1.0,
    "merda": -0.9,
    "lag": -0.5,
    "travou": -0.5,
    "caiu": -0.5,
    "bugou": -0.4,
    "perdeu": -0.5,
    "derrota": -0.7,
    "fail": -0.6,
    "aff": -0.5,
    "credo": -0.6,
    "pior": -0.7,
    "😂": 0.6,
    "❤️": 0.8,
    "🔥": 0.7,
    "👏": 0.6,
    "😍": 0.9,
    "🎉": 0.7,
    "😡": -0.8,
    "👎": -0.7,
    "😢": -0.6,
    "💀": 0.3,
}
LAUGH_PATTERN = re.compile(
    r"^(?:k{3,}|(?:ha){2,}h?|(?:rs){2,}|lol|lul|omegalul|kekw)$", re.IGNORECASE
)
LAUGH_SCORE = 0.6
TOKEN_PATTERN = re.compile(r"[0-9a-zà-öø-ÿ_]+|[\U0001F300-\U0001FAFF❤️]", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def message_sentiment(tokens: list[str]) -> float | None:
    """Mean of matched lexicon scores; None when nothing matched (neutral
    messages don't dilute the averages)."""
    scores = []
    for token in tokens:
        if LAUGH_PATTERN.match(token):
            scores.append(LAUGH_SCORE)
            continue
        if token in LEXICON:
            scores.append(LEXICON[token])
    if not scores:
        return None
    return sum(scores) / len(scores)


def emote_names(text: str, emotes: dict | None) -> list[str]:
    """Emote occurrences by name, recovered from the IRC ranges (we store
    emote ids + character ranges; the name is the text slice)."""
    if not emotes:
        return []
    names = []
    for ranges in emotes.values():
        for span in ranges:
            start, _, end = span.partition("-")
            if start.isdigit() and end.isdigit():
                name = text[int(start) : int(end) + 1].strip()
                if name:
                    names.append(name)
    return names


def strip_emotes(text: str, emotes: dict | None) -> str:
    if not emotes:
        return text
    result = list(text)
    for ranges in emotes.values():
        for span in ranges:
            start, _, end = span.partition("-")
            if start.isdigit() and end.isdigit():
                for index in range(int(start), min(int(end) + 1, len(result))):
                    result[index] = " "
    return "".join(result)


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
    minute_sentiment: dict[int, list[float]] = defaultdict(list)
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
        minute = int((sent_at - stream.started_at).total_seconds() // 60)
        minute = min(max(minute, 0), total_minutes - 1)
        minute_counts[(login, minute)] += 1

        for name in emote_names(text, message_emotes):
            emotes[name] += 1
        tokens = tokenize(strip_emotes(text, message_emotes))
        for token in tokens:
            if (
                len(token) >= MIN_WORD_LENGTH
                and token not in STOPWORDS
                and not token.isdigit()
                and not LAUGH_PATTERN.match(token)
            ):
                words[token] += 1
        score = message_sentiment(tokens)
        if score is not None:
            all_scores.append(score)
            minute_sentiment[minute].append(score)
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
                t=stream.started_at + timedelta(minutes=minute),
                score=round(sum(scores) / len(scores), 2),
                messages=len(scores),
            )
            for minute, scores in sorted(minute_sentiment.items())
        ],
        sentiment_by_chatter=[
            ChatterSentiment(login=login, score=round(sum(scores) / len(scores), 2))
            for login, scores in sorted(
                login_sentiment.items(), key=lambda item: len(item[1]), reverse=True
            )[:SHARE_SLICES]
        ],
        presence=_presence(stream, minute_counts, top_logins, total_minutes),
    )
