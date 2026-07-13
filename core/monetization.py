"""Account-level monetization recommendations. The LLM only phrases advice
around numbered SQL facts and must cite the fact numbers that back each one, so
nothing is invented (same grounding rule as the per-stream recommendations)."""

import json
import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from core.llm import LLMBackend, TokenBudget
from core.models import ChannelRecommendation

logger = logging.getLogger(__name__)

RECOMMEND_MAX = 6
RECOMMEND_INPUT_CAP = 4000
RECOMMEND_OUTPUT_TOKENS = 1500


def _parse_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def generate_channel_recommendations(
    db: Session,
    channel_id: int,
    facts: list[str],
    backend: LLMBackend,
    budget: TokenBudget,
) -> int:
    """Replace the channel's recommendation set. `facts` are pre-built numbered
    strings (e.g. "[1] ..."). Returns how many grounded recommendations stored."""
    if not facts:
        return 0
    if not budget.can_afford(
        backend.count_tokens("\n".join(facts)), RECOMMEND_OUTPUT_TOKENS
    ):
        return 0

    prompt = (
        "FATOS de monetização medidos do canal na Twitch (cada um com um número "
        "entre colchetes):\n"
        + "\n".join(facts)
        + "\nCom base SOMENTE nesses fatos, dê recomendações práticas para o "
        "streamer ganhar mais dinheiro (faça mais do que rende, corte o que não "
        'converte). Responda APENAS um JSON válido: {"recommendations": '
        '[{"content": "<recomendação em 1-2 frases, português do Brasil>", '
        '"fact_ids": [números dos fatos que embasam]}]}. Cite pelo menos um número '
        f"de fato por recomendação, máximo {RECOMMEND_MAX}, seja concreto."
    )
    response = backend.generate(prompt, RECOMMEND_OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = _parse_json(response)
    recommendations = parsed.get("recommendations") if parsed else None
    if not isinstance(recommendations, list):
        logger.warning(
            "channel recommendations discarded: unparseable",
            extra={"channel_id": channel_id},
        )
        return 0

    fact_text = {index + 1: fact for index, fact in enumerate(facts)}
    db.execute(
        delete(ChannelRecommendation).where(
            ChannelRecommendation.channel_id == channel_id
        )
    )
    stored = 0
    for item in recommendations[:RECOMMEND_MAX]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        raw_facts = item.get("fact_ids", [])
        cited = (
            [fact_text[n] for n in raw_facts if isinstance(n, int) and n in fact_text]
            if isinstance(raw_facts, list)
            else []
        )
        if not content or not cited:
            logger.warning(
                "channel recommendation discarded: no grounded fact cited",
                extra={"channel_id": channel_id},
            )
            continue
        db.add(
            ChannelRecommendation(
                channel_id=channel_id,
                content=content,
                evidence={"facts": cited},
                model_used=backend.model_name,
            )
        )
        stored += 1
    return stored
