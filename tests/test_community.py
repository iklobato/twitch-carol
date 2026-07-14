"""Community endpoint: lexicon sentiment, word/emote extraction, share,
presence and isolation."""

from datetime import datetime

import pytest

from apps.api.community import SENTIMENT_BUCKET_SECONDS
from core.models import InsightType
from core.text import (
    emote_names,
    emote_occurrences,
    message_sentiment,
    strip_emotes,
    tokenize,
)
from tests.conftest import login_as
from tests.factories import (
    add_chat,
    add_insight,
    add_segment,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_tokenize_handles_accents_and_emoji() -> None:
    assert tokenize("Hoje é DEPLOY na Digital Ocean! 🔥") == [
        "hoje",
        "é",
        "deploy",
        "na",
        "digital",
        "ocean",
        "🔥",
    ]


def test_sentiment_positive_negative_and_neutral() -> None:
    positive = message_sentiment(tokenize("que live incrível, top demais"))
    negative = message_sentiment(tokenize("lag horrível, que lixo"))
    assert positive is not None and positive > 0
    assert negative is not None and negative < 0
    assert message_sentiment(tokenize("qual editor você usa")) is None


def test_sentiment_laughter_counts_as_positive() -> None:
    assert message_sentiment(tokenize("KKKKKK")) == pytest.approx(0.6)
    assert message_sentiment(tokenize("hahaha")) == pytest.approx(0.6)


def test_emote_names_recovered_from_ranges() -> None:
    text = "Kappa muito bom Kappa"
    emotes = {"25": ["0-4", "16-20"]}
    assert emote_names(text, emotes) == ["Kappa", "Kappa"]
    assert emote_occurrences(text, emotes) == [("25", "Kappa"), ("25", "Kappa")]
    assert "Kappa" not in strip_emotes(text, emotes)
    assert emote_names(text, None) == []


def test_community_endpoint_full_payload(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=10)
    add_chat(
        db,
        stream,
        8,
        author="animada",
        text="que live incrível, deploy top",
        spread_seconds=500,
    )
    add_chat(
        db,
        stream,
        3,
        author="bravo",
        text="lag horrível de novo",
        offset_seconds=200,
        spread_seconds=100,
    )
    messages = add_chat(
        db, stream, 2, author="emoter", text="Kappa demais", offset_seconds=400
    )
    for message in messages:
        message.emotes = {"25": ["0-4"]}
    db.flush()

    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/community").json()

    assert body["share"][0]["login"] == "animada"
    assert sum(s["messages"] for s in body["share"]) == 13
    top_words = {w["word"] for w in body["words"]}
    assert "deploy" in top_words
    assert "que" not in top_words  # stopword
    assert body["emotes"] == [{"emote_id": "25", "name": "Kappa", "count": 2}]
    assert body["sentiment_overall"] is not None
    scores = {c["login"]: c["score"] for c in body["sentiment_by_chatter"]}
    assert scores["animada"] > 0
    assert scores["bravo"] < 0
    assert len(body["presence"]["rows"]) == 3
    assert sum(body["presence"]["rows"][0]["cells"]) == 8

    other = make_channel(db)
    login_as(api_client, other)
    assert api_client.get(f"/api/streams/{stream.id}/community").status_code == 404


def test_community_empty_stream(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/community").json()
    assert body["share"] == []
    assert body["sentiment_overall"] is None
    assert body["sentiment_timeline"] == []


def test_sentiment_timeline_buckets_are_30_seconds(api_client, db) -> None:
    assert SENTIMENT_BUCKET_SECONDS == 30
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=5)
    # two positive messages in the first 30s bucket, one negative in the third
    add_chat(
        db,
        stream,
        2,
        author="a",
        text="incrível top demais",
        offset_seconds=5,
        spread_seconds=10,
    )
    add_chat(db, stream, 1, author="b", text="lag horrível lixo", offset_seconds=70)
    db.flush()

    login_as(api_client, channel)
    timeline = api_client.get(f"/api/streams/{stream.id}/community").json()[
        "sentiment_timeline"
    ]

    # buckets land on 30s boundaries relative to stream start
    by_offset = {
        round(
            (datetime.fromisoformat(point["t"]) - stream.started_at).total_seconds()
        ): point
        for point in timeline
    }
    assert set(by_offset) == {0, 60}
    assert by_offset[0]["score"] > 0 and by_offset[0]["messages"] == 2
    assert by_offset[60]["score"] < 0 and by_offset[60]["messages"] == 1


def test_chatter_and_topic_top_words(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=20)
    add_chat(
        db, stream, 6, author="dev", text="deploy deploy caddy", spread_seconds=200
    )
    add_chat(db, stream, 4, author="lurker", text="banana banana", offset_seconds=100)
    segment = add_segment(db, stream, 60, "explicando o deploy")
    topic = add_insight(
        db,
        stream,
        InsightType.TOPIC,
        "Deploy\ndesc",
        {"segment_ids": [segment.id], "message_ids": [], "rank": 1},
    )

    login_as(api_client, channel)
    chatters = api_client.get(f"/api/streams/{stream.id}/chatters").json()
    dev = next(c for c in chatters if c["author_login"] == "dev")
    dev_words = {w["word"]: w["count"] for w in dev["top_words"]}
    assert dev_words["deploy"] == 12
    assert dev_words["caddy"] == 6
    assert "banana" not in dev_words  # a different chatter's word

    detail = api_client.get(f"/api/streams/{stream.id}/topics/{topic.id}").json()
    topic_words = {w["word"] for w in detail["top_words"]}
    assert "deploy" in topic_words


def test_chatter_sentiment_score(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=10)
    add_chat(db, stream, 5, author="feliz", text="que live incrível, top demais")
    add_chat(
        db, stream, 5, author="bravo", text="lag horrível, que lixo", offset_seconds=60
    )
    add_chat(
        db, stream, 3, author="neutro", text="qual editor você usa", offset_seconds=120
    )
    db.flush()

    login_as(api_client, channel)
    chatters = {
        c["author_login"]: c
        for c in api_client.get(f"/api/streams/{stream.id}/chatters").json()
    }
    assert chatters["feliz"]["sentiment_score"] > 0
    assert chatters["bravo"]["sentiment_score"] < 0
    # no lexicon word matched -> no score
    assert chatters["neutro"]["sentiment_score"] is None
