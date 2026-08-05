"""The channel's language decides the text the backend writes for the streamer.

The facts here are not throwaway prompt input: they are stored (recommendation
evidence) and rendered verbatim in the web app, so an English channel getting
Portuguese facts is a visible bug, not a cosmetic one.
"""

import pytest

from core.follower_intel import build_follower_facts
from core.i18n import chat_language, format_number, language_name, resolve, t
from core.models import Follower
from core.monetization import build_monetization_facts
from core.records import RecordMetric, add_record_facts, update_stream_records
from tests.factories import add_chat, add_event, make_channel, make_stream
from workers.analyze.pipeline import _retention_line


def test_every_message_exists_in_both_languages() -> None:
    from core.i18n import _MESSAGES

    for key, variants in _MESSAGES.items():
        assert set(variants) == {"en", "pt"}, key
        assert all(variants.values()), key


def test_a_dropped_placeholder_would_silently_lose_the_number() -> None:
    """Both variants of a message must interpolate the same names: tests catch
    what the type system cannot on the Python side."""
    import re

    from core.i18n import _MESSAGES

    for key, variants in _MESSAGES.items():
        names = {
            lang: set(re.findall(r"\{(\w+)\}", text)) for lang, text in variants.items()
        }
        assert names["en"] == names["pt"], key


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("pt", "pt"),
        ("pt-BR", "pt"),
        ("en", "en"),
        ("en-GB", "en"),
        ("es", "pt"),
        (None, "pt"),
    ],
)
def test_resolve_falls_back_to_portuguese(language: str | None, expected: str) -> None:
    # Portuguese is the fallback on purpose: channels.language defaults to it,
    # and an unknown tag must not produce an empty language downstream.
    assert resolve(language) == expected


def test_language_name_is_spelled_out_for_the_prompt() -> None:
    assert language_name("en") == "English"
    assert language_name("pt-BR") == "Brazilian Portuguese"


def test_number_separators_follow_the_language() -> None:
    assert format_number(12400, "en") == "12,400"
    assert format_number(12400, "pt") == "12.400"
    assert format_number(1234.5, "en", decimals=1) == "1,234.5"
    assert format_number(1234.5, "pt", decimals=1) == "1.234,5"


def test_monetization_facts_are_written_in_the_channel_language(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    # one contributor carrying everything -> the whale-risk fact
    add_event(db, stream, "channel.cheer", amount=1000, login="whale")
    db.flush()

    portuguese = build_monetization_facts(db, channel.id, [stream.id], "pt")
    english = build_monetization_facts(db, channel.id, [stream.id], "en")

    assert any("maior contribuinte" in fact for fact in portuguese)
    assert any("biggest contributor" in fact for fact in english)


def test_follower_facts_are_written_in_the_channel_language(db) -> None:
    channel = make_channel(db)
    for index in range(6):
        db.add(
            Follower(
                channel_id=channel.id,
                twitch_user_id=9000 + index,
                login=f"silent_{index}",
                followed_at=make_stream(db, channel).started_at,
            )
        )
    db.flush()

    portuguese = build_follower_facts(db, channel.id, "pt")
    english = build_follower_facts(db, channel.id, "en")

    assert any("nunca escreveram no chat" in fact for fact in portuguese)
    assert any("never written in chat" in fact for fact in english)


def test_record_facts_and_metric_labels_follow_the_language(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_chat(db, stream, 3)
    db.flush()
    update_stream_records(db, stream)

    portuguese: list[str] = []
    add_record_facts(db, channel.id, [RecordMetric.MESSAGES], portuguese, "pt")
    english: list[str] = []
    add_record_facts(db, channel.id, [RecordMetric.MESSAGES], english, "en")

    assert any("Melhores marcas do canal" in fact for fact in portuguese)
    assert any("mensagens no chat" in fact for fact in portuguese)
    assert any("Channel best marks" in fact for fact in english)
    assert any("chat messages" in fact for fact in english)


def test_retention_line_follows_the_language(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    db.flush()

    assert "você segurou" in _retention_line(db, stream, 80.0, "pt")
    assert "you kept" in _retention_line(db, stream, 80.0, "en")


def test_t_fills_placeholders() -> None:
    assert t("en", "fact.follow_timing", pct=40, weekday="Monday") == (
        "40% of your follows arrive on Monday."
    )


def test_chat_language_follows_the_audio_not_the_sign_up() -> None:
    """A Brazilian streamer signed up in English still types Portuguese in chat.
    Reading it with the English lexicon returns no reaction at all, which is the
    exact failure this split exists to prevent."""
    assert chat_language("pt", "en") == "pt"
    assert chat_language("en", "pt") == "en"


def test_chat_language_falls_back_until_a_live_is_transcribed() -> None:
    assert chat_language(None, "en") == "en"
    assert chat_language(None, "pt") == "pt"
