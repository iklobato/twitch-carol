"""AI over the follower features: segment the base into personas, summarize who
they are from their bios, and draft targeted reactivation nudges.

The rule-based segmentation and target selection are SQL-derived (always
available); the LLM only phrases the action per segment, the audience summary,
and the nudges, grounded in that data. Persisted to follower_ai_insights so the
page reads generated text without running the model per request.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.follower_profiles import FollowerProfile, build_follower_profiles
from core.i18n import language_name
from core.llm import LLMBackend, TokenBudget, parse_json_object
from core.models import Follower, FollowerAiInsight

logger = logging.getLogger(__name__)

KIND_SEGMENT = "segment"
KIND_BIO = "bio_summary"
KIND_REACTIVATION = "reactivation"

AFFILIATE = "affiliate"
PARTNER = "partner"

DORMANT_DAYS = 30
RECENT_FOLLOW_DAYS = 30
REACTIVATION_LIMIT = 8
BIO_SAMPLE = 40
SEGMENT_EXAMPLES = 5
OUTPUT_TOKENS = 1400
MIN_SEGMENT_SIZE = 1


@dataclass
class SegmentMember:
    login: str
    display_name: str | None


@dataclass
class Segment:
    key: str
    label: str
    description: str
    count: int
    examples: list[str]
    members: list[SegmentMember]


def _is_streamer(p: FollowerProfile, now: datetime) -> bool:
    return p.broadcaster_type in (AFFILIATE, PARTNER)


def _is_paying_fan(p: FollowerProfile, now: datetime) -> bool:
    return p.estimated_usd > 0 and p.messages > 0


def _is_dormant(p: FollowerProfile, now: datetime) -> bool:
    return (
        p.messages > 0
        and p.last_seen is not None
        and (now - p.last_seen).days >= DORMANT_DAYS
    )


def _is_engaged(p: FollowerProfile, now: datetime) -> bool:
    return p.messages > 0


def _is_newcomer(p: FollowerProfile, now: datetime) -> bool:
    return (now - p.followed_at).days < RECENT_FOLLOW_DAYS


def _is_lurker(p: FollowerProfile, now: datetime) -> bool:
    return True  # everyone left over: followed, never chatted, not new


# Ordered: each follower falls into the first segment whose predicate matches.
# (key, label, description, predicate). Label and description are English on
# purpose: they are prompt context, never shown. The web app words each
# persona from its key, in the reader's language.
_SEGMENT_RULES: list[
    tuple[str, str, str, Callable[[FollowerProfile, datetime], bool]]
] = [
    ("streamers", "Streamers", "Affiliates/partners who follow you", _is_streamer),
    ("paying_fans", "Paying fans", "They chat and have already paid", _is_paying_fan),
    ("dormant", "Gone quiet", "Chatted before, absent for a while", _is_dormant),
    ("engaged", "Engaged", "They chat, have not paid yet", _is_engaged),
    ("newcomers", "Newcomers", "Followed recently, no interaction yet", _is_newcomer),
    ("lurkers", "Lurkers", "They follow and only watch", _is_lurker),
]


def _classify(profile: FollowerProfile, now: datetime) -> str:
    for key, _label, _desc, predicate in _SEGMENT_RULES:
        if predicate(profile, now):
            return key
    return "lurkers"


def build_segments(
    profiles: list[FollowerProfile], now: datetime | None = None
) -> list[Segment]:
    """Assign each follower to exactly one persona and summarize the groups."""
    reference = now if now is not None else datetime.now(UTC)
    members: dict[str, list[FollowerProfile]] = {key: [] for key, *_ in _SEGMENT_RULES}
    for profile in profiles:
        members[_classify(profile, reference)].append(profile)
    segments: list[Segment] = []
    for key, label, description, _ in _SEGMENT_RULES:
        group = members[key]
        if len(group) < MIN_SEGMENT_SIZE:
            continue
        segments.append(
            Segment(
                key=key,
                label=label,
                description=description,
                count=len(group),
                examples=[p.display_name or p.login for p in group[:SEGMENT_EXAMPLES]],
                members=[
                    SegmentMember(login=p.login, display_name=p.display_name)
                    for p in group
                ],
            )
        )
    return segments


def reactivation_targets(
    profiles: list[FollowerProfile], now: datetime | None = None
) -> list[FollowerProfile]:
    """Followers worth winning back: engaged before, quiet now, ranked by the
    value/engagement they used to bring."""
    reference = now if now is not None else datetime.now(UTC)
    dormant = [p for p in profiles if _is_dormant(p, reference)]
    dormant.sort(key=lambda p: (p.estimated_usd, p.messages), reverse=True)
    return dormant[:REACTIVATION_LIMIT]


def _bio_sample(db: Session, channel_id: int) -> list[str]:
    rows = db.scalars(
        select(Follower.description)
        .where(Follower.channel_id == channel_id)
        .where(Follower.description.is_not(None))
        .where(Follower.description != "")
        .limit(BIO_SAMPLE)
    )
    return [bio.strip() for bio in rows if bio and bio.strip()]


def generate_follower_ai(
    db: Session,
    channel_id: int,
    backend: LLMBackend,
    budget: TokenBudget,
    language: str | None = None,
) -> int:
    """Regenerate the channel's follower AI insights (segment actions, bio
    summary, reactivation nudges). Returns how many rows were stored."""
    profiles = build_follower_profiles(db, channel_id)
    if not profiles:
        return 0
    now = datetime.now(UTC)
    segments = build_segments(profiles, now)
    targets = reactivation_targets(profiles, now)
    bios = _bio_sample(db, channel_id)

    prompt = _build_prompt(segments, targets, bios, language)
    if not budget.can_afford(backend.count_tokens(prompt), OUTPUT_TOKENS):
        return 0
    response = backend.generate(prompt, OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = parse_json_object(response)
    if parsed is None:
        logger.warning(
            "follower AI discarded: unparseable", extra={"channel_id": channel_id}
        )
        return 0

    db.execute(
        delete(FollowerAiInsight).where(FollowerAiInsight.channel_id == channel_id)
    )
    stored = _store(db, channel_id, backend, segments, parsed)
    return stored


def _build_prompt(
    segments: list[Segment],
    targets: list[FollowerProfile],
    bios: list[str],
    language: str | None,
) -> str:
    segment_lines = "\n".join(
        f"- {s.key} ({s.count}): {s.label}, {s.description}" for s in segments
    )
    target_lines = "\n".join(
        f"- {p.display_name or p.login}: {p.messages} msgs, US$ {p.estimated_usd}"
        for p in targets
    )
    bio_lines = "\n".join(f"- {bio}" for bio in bios[:BIO_SAMPLE])
    # English prompt whatever the channel speaks; only the answer is localized.
    written_in = f"written in {language_name(language)}"
    return (
        "You analyse the follower base of a Twitch streamer.\n\n"
        f"SEGMENTS (key, size, name, description):\n{segment_lines or '- (none)'}\n\n"
        f"LAPSED FOLLOWERS to bring back:\n{target_lines or '- (none)'}\n\n"
        f"FOLLOWER BIOS (sample):\n{bio_lines or '- (none)'}\n\n"
        "Reply with valid JSON ONLY, three keys:\n"
        '{"segment_actions": [{"key": "<segment key exactly as listed>", '
        f'"action": "<1 practical action, {written_in}>"}}], '
        f'"audience_summary": "<2-3 sentences {written_in} about who follows '
        'this channel, based on the bios>", '
        '"reactivations": [{"login_or_name": "<who>", "message": "<short, '
        f'personal message to bring them back, {written_in}>"}}]}}. '
        "Use only the data above, be concrete."
    )


def _store(
    db: Session,
    channel_id: int,
    backend: LLMBackend,
    segments: list[Segment],
    parsed: dict,
) -> int:
    stored = 0
    stored += _store_segment_actions(db, channel_id, backend, segments, parsed)
    stored += _store_bio_summary(db, channel_id, backend, parsed)
    stored += _store_reactivations(db, channel_id, backend, parsed)
    return stored


def _store_segment_actions(
    db: Session,
    channel_id: int,
    backend: LLMBackend,
    segments: list[Segment],
    parsed: dict,
) -> int:
    by_key = {s.key: s for s in segments}
    actions = parsed.get("segment_actions")
    if not isinstance(actions, list):
        return 0
    stored = 0
    for item in actions:
        if not isinstance(item, dict):
            continue
        segment = by_key.get(str(item.get("key", "")).strip())
        action = str(item.get("action", "")).strip()
        if segment is None or not action:
            continue
        db.add(
            FollowerAiInsight(
                channel_id=channel_id,
                kind=KIND_SEGMENT,
                title=segment.key,
                content=action,
                evidence={
                    "count": segment.count,
                    "description": segment.description,
                    "examples": segment.examples,
                },
                model_used=backend.model_name,
            )
        )
        stored += 1
    return stored


def _store_bio_summary(
    db: Session, channel_id: int, backend: LLMBackend, parsed: dict
) -> int:
    summary = str(parsed.get("audience_summary", "")).strip()
    if not summary:
        return 0
    db.add(
        FollowerAiInsight(
            channel_id=channel_id,
            kind=KIND_BIO,
            title=None,
            content=summary,
            evidence={},
            model_used=backend.model_name,
        )
    )
    return 1


def _store_reactivations(
    db: Session, channel_id: int, backend: LLMBackend, parsed: dict
) -> int:
    items = parsed.get("reactivations")
    if not isinstance(items, list):
        return 0
    stored = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        who = str(item.get("login_or_name", "")).strip()
        message = str(item.get("message", "")).strip()
        if not who or not message:
            continue
        db.add(
            FollowerAiInsight(
                channel_id=channel_id,
                kind=KIND_REACTIVATION,
                title=who,
                content=message,
                evidence={},
                model_used=backend.model_name,
            )
        )
        stored += 1
    return stored
