"""Account-level LLM monetization recommendations, grounded in numbered facts."""

import json
import re

import pytest
from sqlalchemy import select

import apps.api.channel as channel_api
from core.llm import TokenBudget
from core.models import ChannelRecommendation
from core.monetization import generate_channel_recommendations
from tests.conftest import login_as
from tests.factories import add_event, make_channel, make_stream

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


def test_recommendations_endpoint_generates_and_overview_returns(
    api_client, db, monkeypatch
) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    cheer = add_event(db, stream, "channel.cheer", offset_seconds=60, amount=3000)
    cheer.payload = {"user_login": "baleia"}
    db.flush()

    monkeypatch.setattr(channel_api, "get_llm_backend", lambda: GroundedFakeLLM())
    login_as(api_client, channel)

    created = api_client.post("/api/channel/recommendations").json()
    assert len(created) == 1
    assert created[0]["facts"]

    overview = api_client.get("/api/channel").json()
    assert overview["recommendations"] == created
