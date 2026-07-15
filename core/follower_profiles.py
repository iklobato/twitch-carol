"""Per-follower feature rows: cross the enriched follower base with captured
chat, money events, and subscriptions to answer "who are they, individually".

This is the shared foundation the follower page (drill-down, whales, funnel,
cohorts, badge tenure) and later the AI segments read from. Everything here is
SQL; no Twitch calls.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.finance import MONEY_EVENT_TYPES, event_contributor, event_usd
from core.models import ChatMessage, Event, Follower, Subscription

SUBSCRIBER_BADGE = "subscriber"
FOUNDER_BADGE = "founder"


@dataclass
class FollowerProfile:
    """One follower crossed with everything captured about them."""

    login: str
    display_name: str | None
    followed_at: datetime
    broadcaster_type: str | None
    messages: int = 0
    streams_present: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    estimated_usd: float = 0.0
    is_subscriber: bool = False
    sub_months: int = 0

    @property
    def stage(self) -> str:
        """Where the follower sits in the funnel. Each stage implies the ones
        before it, so this reads the deepest reached."""
        if self.estimated_usd > 0:
            return "pagante"
        if self.is_subscriber:
            return "inscrito"
        if self.messages > 0:
            return "engajado"
        return "seguidor"


@dataclass
class _ChatAgg:
    messages: int = 0
    streams: set[int] = field(default_factory=set)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    sub_months: int = 0


def build_follower_profiles(db: Session, channel_id: int) -> list[FollowerProfile]:
    """One row per follower, joined (by login) to their captured chat, money,
    and subscription state. Ordered by estimated value, then messages."""
    followers = list(
        db.scalars(select(Follower).where(Follower.channel_id == channel_id))
    )
    if not followers:
        return []

    chat = _chat_by_login(db, channel_id)
    value = _value_by_login(db, channel_id)
    subs = _subscriber_months(db, channel_id)

    profiles = [
        _assemble(follower, chat.get(follower.login), value, subs)
        for follower in followers
    ]
    profiles.sort(key=lambda p: (p.estimated_usd, p.messages), reverse=True)
    return profiles


def _assemble(
    follower: Follower,
    chat: "_ChatAgg | None",
    value: dict[str, float],
    subs: dict[str, int],
) -> FollowerProfile:
    profile = FollowerProfile(
        login=follower.login,
        display_name=follower.display_name,
        followed_at=follower.followed_at,
        broadcaster_type=follower.broadcaster_type,
        estimated_usd=round(value.get(follower.login, 0.0), 2),
    )
    if chat is not None:
        profile.messages = chat.messages
        profile.streams_present = len(chat.streams)
        profile.first_seen = chat.first_seen
        profile.last_seen = chat.last_seen
    months = max(subs.get(follower.login, 0), chat.sub_months if chat else 0)
    profile.sub_months = months
    profile.is_subscriber = follower.login in subs or months > 0
    return profile


def _chat_by_login(db: Session, channel_id: int) -> dict[str, _ChatAgg]:
    """Per-login chat aggregates in one pass: message count, distinct streams,
    first/last seen, and the deepest subscriber-badge tenure seen."""
    rows = db.execute(
        select(
            ChatMessage.author_login,
            ChatMessage.sent_at,
            ChatMessage.stream_id,
            ChatMessage.badges,
        ).where(ChatMessage.channel_id == channel_id)
    ).yield_per(5000)

    agg: dict[str, _ChatAgg] = defaultdict(_ChatAgg)
    for login, sent_at, stream_id, badges in rows:
        entry = agg[login]
        entry.messages += 1
        entry.streams.add(stream_id)
        if entry.first_seen is None or sent_at < entry.first_seen:
            entry.first_seen = sent_at
        if entry.last_seen is None or sent_at > entry.last_seen:
            entry.last_seen = sent_at
        entry.sub_months = max(entry.sub_months, _badge_months(badges))
    return agg


def _badge_months(badges: dict | None) -> int:
    """The subscriber/founder badge version is the tenure in months."""
    if not badges:
        return 0
    for key in (SUBSCRIBER_BADGE, FOUNDER_BADGE):
        raw = badges.get(key)
        if raw is not None and str(raw).isdigit():
            return int(raw)
    return 0


def _value_by_login(db: Session, channel_id: int) -> dict[str, float]:
    """Estimated USD each login has contributed via bits/subs/gifts."""
    value: dict[str, float] = defaultdict(float)
    for event in db.scalars(
        select(Event)
        .where(Event.channel_id == channel_id)
        .where(Event.type.in_(MONEY_EVENT_TYPES))
    ):
        login = event_contributor(event)
        if login:
            value[login] += event_usd(event)
    return value


def _subscriber_months(db: Session, channel_id: int) -> dict[str, int]:
    """Current subscribers from the Helix snapshot (tenure unknown here, so 0;
    chat badges fill tenure in when present)."""
    return {
        login: 0
        for login in db.scalars(
            select(Subscription.login).where(Subscription.channel_id == channel_id)
        )
    }
