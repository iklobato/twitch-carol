"""Minimal Twitch IRC (TMI) support: anonymous connection and PRIVMSG parsing.

Twitch IRC lines look like:
@badges=subscriber/3;emotes=25:0-4;id=<uuid>;tmi-sent-ts=1720000000000;... \
:nick!nick@nick.tmi.twitch.tv PRIVMSG #channel :message text
"""

import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667

# Reconnect backoff: worst single wait is RECONNECT_CAP_SECONDS + jitter,
# keeping chat loss per connection blip well under the 60s product rule.
RECONNECT_BASE_SECONDS = 1.0
RECONNECT_CAP_SECONDS = 15.0
RECONNECT_JITTER = 0.2


@dataclass
class ParsedChat:
    message_id: str | None
    author_id: str
    author_login: str
    badges: dict[str, str] = field(default_factory=dict)
    emotes: dict[str, list[str]] = field(default_factory=dict)
    text: str = ""
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def anonymous_nick() -> str:
    return f"justinfan{random.randint(10000, 99999)}"


def backoff_delays() -> Iterator[float]:
    delay = RECONNECT_BASE_SECONDS
    while True:
        jitter = 1 + random.uniform(-RECONNECT_JITTER, RECONNECT_JITTER)
        yield min(delay, RECONNECT_CAP_SECONDS) * jitter
        delay = min(delay * 2, RECONNECT_CAP_SECONDS)


def parse_tags(raw_tags: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for pair in raw_tags.split(";"):
        key, _, value = pair.partition("=")
        tags[key] = value
    return tags


def parse_badges(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    badges: dict[str, str] = {}
    for item in raw.split(","):
        name, _, version = item.partition("/")
        badges[name] = version
    return badges


def parse_emotes(raw: str) -> dict[str, list[str]]:
    if not raw:
        return {}
    emotes: dict[str, list[str]] = {}
    for item in raw.split("/"):
        emote_id, _, positions = item.partition(":")
        emotes[emote_id] = positions.split(",") if positions else []
    return emotes


def parse_privmsg(line: str) -> ParsedChat | None:
    """Returns None for anything that is not a parseable PRIVMSG."""
    tags: dict[str, str] = {}
    rest = line.strip()
    if rest.startswith("@"):
        raw_tags, _, rest = rest[1:].partition(" ")
        tags = parse_tags(raw_tags)
    if " PRIVMSG #" not in rest or not rest.startswith(":"):
        return None
    prefix, _, remainder = rest[1:].partition(" PRIVMSG #")
    login = prefix.split("!", 1)[0]
    _, _, text = remainder.partition(" :")

    sent_at = datetime.now(UTC)
    raw_ts = tags.get("tmi-sent-ts", "")
    if raw_ts.isdigit():
        sent_at = datetime.fromtimestamp(int(raw_ts) / 1000, tz=UTC)

    return ParsedChat(
        message_id=tags.get("id"),
        author_id=tags.get("user-id", ""),
        author_login=login,
        badges=parse_badges(tags.get("badges", "")),
        emotes=parse_emotes(tags.get("emotes", "")),
        text=text,
        sent_at=sent_at,
    )
