"""Community endpoint: lexicon sentiment, word/emote extraction, share,
presence and isolation."""

import pytest

from apps.api.community import emote_names, message_sentiment, strip_emotes, tokenize
from tests.conftest import login_as
from tests.factories import add_chat, make_channel, make_stream

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
    assert body["emotes"] == [{"name": "Kappa", "count": 2}]
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
