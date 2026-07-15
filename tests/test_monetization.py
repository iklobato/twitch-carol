"""Account-level LLM monetization recommendations, grounded in numbered facts."""

import json
import re

import pytest
from sqlalchemy import select

from core.llm import TokenBudget
from core.models import ChannelRecommendation
from core.monetization import build_monetization_facts, generate_channel_recommendations
from tests.factories import add_event, add_subscription, make_channel, make_stream

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
                        "content": "Faça mais blocos do assunto que mais rende.",
                        "fact_ids": numbers[:1],
                    }
                ]
            }
        )


class UngroundedFakeLLM(GroundedFakeLLM):
    model_name = "ungrounded-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        return json.dumps(
            {"recommendations": [{"content": "Inventei isso.", "fact_ids": [999]}]}
        )


def test_generate_stores_grounded_recommendations(db) -> None:
    channel = make_channel(db)
    facts = [
        "[1] Receita estimada total: US$ 44.50.",
        "[2] O assunto 'Deploy' gerou US$ 30.",
    ]
    backend = GroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1500)

    stored = generate_channel_recommendations(db, channel.id, facts, backend, budget)
    db.flush()

    assert stored == 1
    rec = db.scalar(
        select(ChannelRecommendation).where(
            ChannelRecommendation.channel_id == channel.id
        )
    )
    assert rec.content == "Faça mais blocos do assunto que mais rende."
    assert rec.evidence["facts"] == ["[1] Receita estimada total: US$ 44.50."]
    assert rec.model_used == "grounded-fake"


def test_ungrounded_recommendation_is_discarded(db) -> None:
    channel = make_channel(db)
    facts = ["[1] Receita estimada total: US$ 10.00."]
    backend = UngroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1500)

    stored = generate_channel_recommendations(db, channel.id, facts, backend, budget)
    db.flush()
    assert stored == 0  # cited fact 999 does not exist


def test_generate_replaces_previous_set(db) -> None:
    channel = make_channel(db)
    facts = ["[1] Receita estimada total: US$ 5.00."]
    backend = GroundedFakeLLM()

    generate_channel_recommendations(
        db, channel.id, facts, backend, TokenBudget(backend, 4000, 1500)
    )
    generate_channel_recommendations(
        db, channel.id, facts, backend, TokenBudget(backend, 4000, 1500)
    )
    db.flush()
    count = len(
        db.scalars(
            select(ChannelRecommendation).where(
                ChannelRecommendation.channel_id == channel.id
            )
        ).all()
    )
    assert count == 1  # not duplicated


def test_whale_concentration_fact(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    cheer = add_event(db, stream, "channel.cheer", offset_seconds=60, amount=3000)
    cheer.payload = {"user_login": "baleia"}
    db.flush()

    facts = build_monetization_facts(db, channel.id, [stream.id])

    joined = " ".join(facts)
    assert facts[0].startswith("[1]")
    assert "baleia" in joined
    assert "concentra 100%" in joined  # comparative: share crossed the risk line


def test_category_efficiency_is_comparative(db) -> None:
    channel = make_channel(db)
    rich = make_stream(db, channel, duration_minutes=60)
    rich.category = "Slots"
    poor = make_stream(db, channel, duration_minutes=60)
    poor.category = "Just Chatting"
    # US$100/h for Slots vs US$10/h for Just Chatting; channel average is US$55/h
    a = add_event(db, rich, "channel.cheer", offset_seconds=60, amount=10000)
    a.payload = {"user_login": "fan_a"}
    b = add_event(db, poor, "channel.cheer", offset_seconds=60, amount=1000)
    b.payload = {"user_login": "fan_b"}
    db.flush()

    facts = build_monetization_facts(db, channel.id, [rich.id, poor.id])

    assert any("Slots" in fact and "média" in fact for fact in facts)
    assert not any("Just Chatting" in fact and "/h" in fact for fact in facts)


def test_subscriber_trend_shows_gained_versus_lost(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    add_event(db, stream, "channel.subscribe", offset_seconds=10)
    add_event(db, stream, "channel.subscribe", offset_seconds=20)
    add_event(db, stream, "channel.subscription.end", offset_seconds=30)
    db.flush()

    facts = build_monetization_facts(db, channel.id, [stream.id])

    joined = " ".join(facts)
    assert "ganhou 2 e perdeu 1" in joined
    assert "saldo +1" in joined


def test_no_bare_total_facts_reach_the_llm(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    stream.category = "Just Chatting"
    cheer = add_event(db, stream, "channel.cheer", offset_seconds=60, amount=3000)
    cheer.payload = {"user_login": "baleia"}
    add_subscription(db, channel, "sub_a", tier="1000")
    db.flush()

    joined = " ".join(build_monetization_facts(db, channel.id, [stream.id]))

    # these are tautological bases (restate the metric); they must stay out
    assert "Receita estimada total" not in joined
    assert "assinantes ativos" not in joined


def test_facts_and_generate_are_the_worker_path(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    cheer = add_event(db, stream, "channel.cheer", offset_seconds=60, amount=1000)
    cheer.payload = {"user_login": "fan"}
    db.flush()

    backend = GroundedFakeLLM()
    facts = build_monetization_facts(db, channel.id, [stream.id])
    stored = generate_channel_recommendations(
        db, channel.id, facts, backend, TokenBudget(backend, 4000, 1500)
    )
    db.flush()
    assert stored == 1
    rec = db.scalar(
        select(ChannelRecommendation).where(
            ChannelRecommendation.channel_id == channel.id
        )
    )
    assert rec.evidence["facts"][0].startswith("[1]")
