"""Follower-base facts and the LLM decisions grounded in them."""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from core.follower_intel import build_follower_facts, generate_follower_recommendations
from core.llm import TokenBudget
from core.models import FollowerRecommendation
from tests.factories import add_chat, add_follower, make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


class GroundedFakeLLM:
    model_name = "grounded-fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        numbers = [int(m) for m in re.findall(r"\[(\d+)\]", prompt)]
        return json.dumps(
            {
                "recommendations": [
                    {
                        "content": "Reative seus seguidores silenciosos.",
                        "fact_ids": numbers[:1],
                    }
                ]
            }
        )


class UngroundedFakeLLM(GroundedFakeLLM):
    model_name = "ungrounded-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        return json.dumps(
            {"recommendations": [{"content": "Inventei.", "fact_ids": [999]}]}
        )


def _seed_base(db):
    channel = make_channel(db)
    old = datetime.now(UTC) - timedelta(days=800)
    young = datetime.now(UTC) - timedelta(days=10)
    add_follower(
        db, channel, "ana", broadcaster_type="affiliate", account_created_at=old
    )
    add_follower(
        db, channel, "bruno", broadcaster_type="partner", account_created_at=old
    )
    add_follower(
        db, channel, "caio", broadcaster_type="affiliate", account_created_at=young
    )
    add_follower(db, channel, "duda", account_created_at=young)
    add_follower(db, channel, "edu", account_created_at=old)
    add_follower(db, channel, "fabi", account_created_at=old)
    # ana and bruno are the only ones who ever chatted
    stream = make_stream(db, channel)
    add_chat(db, stream, 3, author="ana")
    add_chat(db, stream, 2, author="bruno")
    db.flush()
    return channel


def test_build_facts_covers_the_four_decision_areas(db) -> None:
    channel = _seed_base(db)
    facts = build_follower_facts(db, channel.id)
    joined = " ".join(facts)

    assert "nunca escreveram no chat" in joined  # reactivation
    assert "afiliados" in joined and "parceiros" in joined  # collab
    assert "follow-bot" in joined  # 2 of 6 young accounts -> 33% >= threshold
    assert "follows chegam na" in joined  # timing


def test_facts_empty_below_minimum_followers(db) -> None:
    channel = make_channel(db)
    add_follower(db, channel, "ana")
    db.flush()
    assert build_follower_facts(db, channel.id) == []


def test_generate_stores_grounded_recommendations(db) -> None:
    channel = _seed_base(db)
    facts = build_follower_facts(db, channel.id)
    backend = GroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1200)

    stored = generate_follower_recommendations(db, channel.id, facts, backend, budget)
    db.flush()

    assert stored == 1
    rec = db.scalar(
        select(FollowerRecommendation).where(
            FollowerRecommendation.channel_id == channel.id
        )
    )
    assert rec.evidence["facts"]  # a real fact was cited
    assert rec.model_used == "grounded-fake"


def test_generate_discards_ungrounded(db) -> None:
    channel = _seed_base(db)
    facts = build_follower_facts(db, channel.id)
    backend = UngroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1200)

    stored = generate_follower_recommendations(db, channel.id, facts, backend, budget)
    db.flush()

    assert stored == 0
    assert (
        db.scalar(
            select(FollowerRecommendation).where(
                FollowerRecommendation.channel_id == channel.id
            )
        )
        is None
    )
