"""Account-level follower intelligence: SQL-derived facts about the follower
base and LLM advice grounded in them. Same grounding rule as core.monetization:
the model only phrases advice around numbered facts and must cite the numbers,
so nothing is invented.

The facts cover four decision areas the streamer asked for: reactivation of
silent followers, collab candidates (followers who are themselves streamers),
fake-follow risk (very young accounts), and timing (when follows arrive)."""

import json
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.llm import LLMBackend, TokenBudget
from core.models import ChatMessage, Follower, FollowerRecommendation

logger = logging.getLogger(__name__)

RECOMMEND_MAX = 5
RECOMMEND_OUTPUT_TOKENS = 1200

# Below this many followers the shares are too noisy to advise on.
MIN_FOLLOWERS_FOR_STATS = 5
# An account that followed within this many days of being created is a common
# follow-bot signature; a high share of these points at bought/fake follows.
NEW_ACCOUNT_DAYS = 30
NEW_ACCOUNT_SHARE_MIN = 0.15

AFFILIATE = "affiliate"
PARTNER = "partner"
WEEKDAY_LABELS = [
    "segunda",
    "terça",
    "quarta",
    "quinta",
    "sexta",
    "sábado",
    "domingo",
]


def build_follower_facts(db: Session, channel_id: int) -> list[str]:
    """Numbered, SQL-derived facts about the channel's followers. Each helper
    only appends when the data is there and the comparison is meaningful."""
    facts: list[str] = []

    def add(text: str) -> None:
        facts.append(f"[{len(facts) + 1}] {text}")

    followers = list(
        db.scalars(select(Follower).where(Follower.channel_id == channel_id))
    )
    if len(followers) < MIN_FOLLOWERS_FOR_STATS:
        return facts

    _add_silent_share(db, channel_id, followers, add)
    _add_streamer_followers(followers, add)
    _add_young_account_share(followers, add)
    _add_follow_timing(followers, add)
    return facts


def _add_silent_share(
    db: Session, channel_id: int, followers: list[Follower], add
) -> None:
    """How many followers never wrote in chat: the reactivation target."""
    chatters = set(
        db.scalars(
            select(func.distinct(ChatMessage.author_login)).where(
                ChatMessage.channel_id == channel_id
            )
        )
    )
    silent = sum(1 for follower in followers if follower.login not in chatters)
    total = len(followers)
    add(
        f"{silent} dos seus {total} seguidores ({round(silent / total * 100)}%) "
        "nunca escreveram no chat."
    )


def _add_streamer_followers(followers: list[Follower], add) -> None:
    """Followers who are themselves affiliates/partners: collab candidates."""
    affiliates = sum(1 for f in followers if f.broadcaster_type == AFFILIATE)
    partners = sum(1 for f in followers if f.broadcaster_type == PARTNER)
    if affiliates + partners == 0:
        return
    add(
        f"{affiliates} seguidores são afiliados e {partners} são parceiros da "
        "Twitch (ou seja, streamers, candidatos a collab)."
    )


def _add_young_account_share(followers: list[Follower], add) -> None:
    """Share of followers who followed within NEW_ACCOUNT_DAYS of creating their
    account: a high value suggests bought or bot follows."""
    account_ages_at_follow = [
        (f.followed_at - f.account_created_at).days
        for f in followers
        if f.account_created_at is not None
    ]
    if len(account_ages_at_follow) < MIN_FOLLOWERS_FOR_STATS:
        return
    young = sum(1 for age in account_ages_at_follow if age < NEW_ACCOUNT_DAYS)
    share = young / len(account_ages_at_follow)
    if share < NEW_ACCOUNT_SHARE_MIN:
        return
    add(
        f"{round(share * 100)}% dos seguidores seguiram com contas de menos de "
        f"{NEW_ACCOUNT_DAYS} dias (possível follow-bot ou follows comprados)."
    )


def _add_follow_timing(followers: list[Follower], add) -> None:
    """Weekday that concentrates the most follows: a timing signal for when new
    people find the channel."""
    counts = [0] * 7
    for follower in followers:
        counts[follower.followed_at.weekday()] += 1
    total = sum(counts)
    best = max(range(7), key=lambda day: counts[day])
    share = counts[best] / total
    add(f"{round(share * 100)}% dos seus follows chegam na {WEEKDAY_LABELS[best]}.")


def _parse_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def generate_follower_recommendations(
    db: Session,
    channel_id: int,
    facts: list[str],
    backend: LLMBackend,
    budget: TokenBudget,
) -> int:
    """Replace the channel's follower-recommendation set. Returns how many
    grounded recommendations were stored."""
    if not facts:
        return 0
    if not budget.can_afford(
        backend.count_tokens("\n".join(facts)), RECOMMEND_OUTPUT_TOKENS
    ):
        return 0

    prompt = (
        "FATOS medidos sobre os seguidores do canal na Twitch (cada um com um "
        "número entre colchetes):\n"
        + "\n".join(facts)
        + "\nCom base SOMENTE nesses fatos, dê decisões práticas sobre a base de "
        "seguidores: reativar quem não engaja, aproveitar streamers que seguem "
        "(collab), reagir a follows suspeitos, e usar o momento em que os follows "
        'chegam. Responda APENAS um JSON válido: {"recommendations": '
        '[{"content": "<decisão em 1-2 frases, português do Brasil>", '
        '"fact_ids": [números dos fatos que embasam]}]}. Cite pelo menos um '
        f"número de fato por decisão, máximo {RECOMMEND_MAX}, seja concreto."
    )
    response = backend.generate(prompt, RECOMMEND_OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = _parse_json(response)
    recommendations = parsed.get("recommendations") if parsed else None
    if not isinstance(recommendations, list):
        logger.warning(
            "follower recommendations discarded: unparseable",
            extra={"channel_id": channel_id},
        )
        return 0

    fact_text = {index + 1: fact for index, fact in enumerate(facts)}
    db.execute(
        delete(FollowerRecommendation).where(
            FollowerRecommendation.channel_id == channel_id
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
                "follower recommendation discarded: no grounded fact cited",
                extra={"channel_id": channel_id},
            )
            continue
        db.add(
            FollowerRecommendation(
                channel_id=channel_id,
                content=content,
                evidence={"facts": cited},
                model_used=backend.model_name,
            )
        )
        stored += 1
    return stored
