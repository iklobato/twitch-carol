"""AI over follower features: segmentation, bio summary, reactivation nudges."""

import json

import pytest
from sqlalchemy import select

from core.follower_ai import (
    KIND_BIO,
    KIND_REACTIVATION,
    KIND_SEGMENT,
    build_segments,
    generate_follower_ai,
    reactivation_targets,
)
from core.follower_profiles import build_follower_profiles
from core.llm import TokenBudget
from core.models import FollowerAiInsight
from tests.factories import add_chat, add_follower, make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


class FakeLLM:
    model_name = "fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        return json.dumps(
            {
                "segment_actions": [
                    {"label": "Sumidos", "action": "Faça um sorteio para quem voltar."}
                ],
                "audience_summary": "Público majoritariamente de games competitivos.",
                "reactivations": [
                    {"login_or_name": "sumido", "message": "Sentimos sua falta!"}
                ],
            }
        )


def _channel_with_segments(db):
    channel = make_channel(db)
    # a dormant chatter: chatted only in a stream from 31 days ago (>= the
    # dormant threshold, and within the partition the pg fixture creates)
    add_follower(db, channel, "sumido")
    old_stream = make_stream(db, channel, started_minutes_ago=31 * 24 * 60)
    add_chat(db, old_stream, 3, author="sumido")
    # a streamer follower, a newcomer, a lurker
    add_follower(db, channel, "streamerx", broadcaster_type="affiliate")
    add_follower(db, channel, "novato", followed_minutes_ago=60)
    add_follower(db, channel, "lurker", followed_minutes_ago=400 * 24 * 60)
    db.flush()
    return channel


def test_build_segments_assigns_each_follower_once(db) -> None:
    channel = _channel_with_segments(db)
    profiles = build_follower_profiles(db, channel.id)
    segments = build_segments(profiles)

    keys = {s.key for s in segments}
    assert "streamers" in keys
    assert "dormant" in keys
    # counts sum to the follower total (partition)
    assert sum(s.count for s in segments) == len(profiles)


def test_reactivation_targets_are_dormant_chatters(db) -> None:
    channel = _channel_with_segments(db)
    profiles = build_follower_profiles(db, channel.id)
    targets = reactivation_targets(profiles)
    logins = {p.login for p in targets}
    assert "sumido" in logins
    assert "lurker" not in logins  # never chatted -> not a reactivation target


def test_generate_persists_segment_bio_and_reactivation(db) -> None:
    channel = _channel_with_segments(db)
    backend = FakeLLM()
    budget = TokenBudget(backend, 8000, 1400)

    stored = generate_follower_ai(db, channel.id, backend, budget)
    db.flush()
    assert stored == 3

    rows = list(
        db.scalars(
            select(FollowerAiInsight).where(FollowerAiInsight.channel_id == channel.id)
        )
    )
    kinds = {r.kind for r in rows}
    assert kinds == {KIND_SEGMENT, KIND_BIO, KIND_REACTIVATION}

    segment = next(r for r in rows if r.kind == KIND_SEGMENT)
    assert segment.title == "Sumidos"
    assert segment.evidence["count"] >= 1

    # regenerating replaces, not appends
    generate_follower_ai(db, channel.id, backend, budget)
    db.flush()
    again = db.scalars(
        select(FollowerAiInsight).where(FollowerAiInsight.channel_id == channel.id)
    ).all()
    assert len(again) == 3


def test_generate_discards_unparseable(db) -> None:
    channel = _channel_with_segments(db)

    class BadLLM(FakeLLM):
        def generate(self, prompt: str, max_tokens: int) -> str:
            return "not json"

    stored = generate_follower_ai(
        db, channel.id, BadLLM(), TokenBudget(BadLLM(), 8000, 1400)
    )
    assert stored == 0


def test_generate_no_followers_returns_zero(db) -> None:
    channel = make_channel(db)
    assert (
        generate_follower_ai(
            db, channel.id, FakeLLM(), TokenBudget(FakeLLM(), 8000, 1400)
        )
        == 0
    )
