from datetime import UTC, datetime
from itertools import islice

from core.irc import (
    RECONNECT_CAP_SECONDS,
    RECONNECT_JITTER,
    backoff_delays,
    parse_badges,
    parse_emotes,
    parse_privmsg,
)

FULL_LINE = (
    "@badge-info=subscriber/8;badges=subscriber/6,premium/1;color=#FF0000;"
    "display-name=Henry;emotes=25:0-4,12-16/1902:6-10;id=abc-123;mod=0;"
    "tmi-sent-ts=1720000000000;user-id=536677125"
    " :henry!henry@henry.tmi.twitch.tv PRIVMSG #somechannel :Kappa Keepo Kappa hello"
)


def test_parse_privmsg_full_tags() -> None:
    parsed = parse_privmsg(FULL_LINE)
    assert parsed is not None
    assert parsed.message_id == "abc-123"
    assert parsed.author_id == "536677125"
    assert parsed.author_login == "henry"
    assert parsed.text == "Kappa Keepo Kappa hello"
    assert parsed.badges == {"subscriber": "6", "premium": "1"}
    assert parsed.emotes == {"25": ["0-4", "12-16"], "1902": ["6-10"]}
    assert parsed.sent_at == datetime.fromtimestamp(1720000000, tz=UTC)


def test_parse_privmsg_message_with_colon() -> None:
    line = (
        "@id=x;user-id=1;tmi-sent-ts=1720000000000"
        " :a!a@a.tmi.twitch.tv PRIVMSG #c :look: https://example.com :)"
    )
    parsed = parse_privmsg(line)
    assert parsed is not None
    assert parsed.text == "look: https://example.com :)"


def test_parse_privmsg_rejects_non_privmsg() -> None:
    assert parse_privmsg("PING :tmi.twitch.tv") is None
    assert parse_privmsg(":tmi.twitch.tv 001 justinfan123 :Welcome, GLHF!") is None
    assert parse_privmsg("") is None


def test_parse_badges_and_emotes_empty() -> None:
    assert parse_badges("") == {}
    assert parse_emotes("") == {}


def test_backoff_grows_and_caps() -> None:
    delays = list(islice(backoff_delays(), 8))
    upper = RECONNECT_CAP_SECONDS * (1 + RECONNECT_JITTER)
    assert all(0 < delay <= upper for delay in delays)
    # after enough doublings every delay sits at the cap (modulo jitter)
    for delay in delays[5:]:
        assert delay >= RECONNECT_CAP_SECONDS * (1 - RECONNECT_JITTER)
