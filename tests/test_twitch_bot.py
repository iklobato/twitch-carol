from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import twitchio

from alerts import AlertKind
from nsfw import NsfwFilter
from twitch_bot import TwitchManager

BOT_ID = "111"
OWNER_ID = "222"


def http_error() -> twitchio.HTTPException:
    return twitchio.HTTPException("nope", status=403, extra="forbidden")


class RecordingCall:
    """Async callable that records kwargs instead of doing I/O.

    Nothing is awaited unless the production code actually calls it, so a
    skipped moderation branch never leaves an un-awaited coroutine behind.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


@pytest.fixture
def make_bot(make_settings, recording_hub):
    def factory(nsfw: NsfwFilter | None = None, **settings_overrides):
        settings = make_settings(
            twitch_bot_id=BOT_ID, twitch_owner_id=OWNER_ID, **settings_overrides
        )
        bot = TwitchManager(settings, recording_hub, nsfw or NsfwFilter([]))
        return bot

    return factory


def sub_payload(gift=False, tier="1000", name="Ana"):
    return SimpleNamespace(
        gift=gift, tier=tier, user=SimpleNamespace(display_name=name)
    )


async def test_constructor_wires_dependencies(make_bot, recording_hub):
    bot = make_bot()
    assert bot._hub is recording_hub
    assert bot.bot_id == BOT_ID


async def test_gift_flagged_subscription_is_skipped(make_bot, recording_hub):
    bot = make_bot()
    await bot.event_subscription(sub_payload(gift=True))
    assert recording_hub.alerts == []


async def test_subscription_alert(make_bot, recording_hub):
    bot = make_bot()
    await bot.event_subscription(sub_payload(tier="2000", name="Ana"))
    [alert] = recording_hub.alerts
    assert alert.kind is AlertKind.SUBSCRIPTION
    assert alert.headline == "Ana assinou!"
    assert alert.detail == "Nova assinatura Tier 2"
    assert alert.username == "Ana"


async def test_subscription_unknown_tier_shows_raw_value(make_bot, recording_hub):
    bot = make_bot()
    await bot.event_subscription(sub_payload(tier="4000"))
    [alert] = recording_hub.alerts
    assert alert.detail == "Nova assinatura 4000"


async def test_resub_alert(make_bot, recording_hub):
    bot = make_bot()
    payload = SimpleNamespace(
        user=SimpleNamespace(display_name="Bea"),
        cumulative_months=5,
        message=SimpleNamespace(text="obrigado!"),
    )
    await bot.event_subscription_message(payload)
    [alert] = recording_hub.alerts
    assert alert.kind is AlertKind.RESUB
    assert alert.headline == "Bea renovou!"
    assert alert.detail == "5 meses - obrigado!"


async def test_resub_empty_message_keeps_trailing_dash(make_bot, recording_hub):
    # Characterization: .strip() only trims whitespace, so an empty resub
    # message leaves "5 meses -". Cosmetic; intentional current behavior.
    bot = make_bot()
    payload = SimpleNamespace(
        user=SimpleNamespace(display_name="Bea"),
        cumulative_months=5,
        message=SimpleNamespace(text=""),
    )
    await bot.event_subscription_message(payload)
    [alert] = recording_hub.alerts
    assert alert.detail == "5 meses -"


@pytest.mark.parametrize(
    ("anonymous", "user"),
    [(True, SimpleNamespace(display_name="Bea")), (False, None)],
)
async def test_gift_anonymous_variants(make_bot, recording_hub, anonymous, user):
    bot = make_bot()
    payload = SimpleNamespace(anonymous=anonymous, user=user, total=3, tier="1000")
    await bot.event_subscription_gift(payload)
    [alert] = recording_hub.alerts
    assert alert.username == "Anonimo"
    assert alert.headline == "Anonimo presenteou 3 sub(s)!"


async def test_gift_alert_with_known_gifter(make_bot, recording_hub):
    bot = make_bot()
    payload = SimpleNamespace(
        anonymous=False,
        user=SimpleNamespace(display_name="Bea"),
        total=5,
        tier="3000",
    )
    await bot.event_subscription_gift(payload)
    [alert] = recording_hub.alerts
    assert alert.kind is AlertKind.GIFT
    assert alert.headline == "Bea presenteou 5 sub(s)!"
    assert alert.detail == "Tier 3 gift"


async def test_announce_without_thank_in_chat_only_broadcasts(
    make_bot, recording_hub, monkeypatch
):
    bot = make_bot(twitch_thank_in_chat=False)
    called = []
    monkeypatch.setattr(
        bot, "create_partialuser", lambda *a, **k: called.append((a, k))
    )
    await bot.event_subscription(sub_payload())
    assert len(recording_hub.alerts) == 1
    assert called == []


async def test_announce_with_thank_in_chat_sends_message(make_bot, monkeypatch):
    bot = make_bot(twitch_thank_in_chat=True)
    sent = []

    class FakeChannel:
        async def send_message(self, *, sender, message):
            sent.append((sender, message))

    requested = []

    def fake_create_partialuser(user_id):
        requested.append(user_id)
        return FakeChannel()

    monkeypatch.setattr(bot, "create_partialuser", fake_create_partialuser)
    await bot.event_subscription(sub_payload(name="Ana"))
    assert requested == [OWNER_ID]
    assert sent == [(BOT_ID, "Ana assinou!")]


async def test_thank_in_chat_swallows_http_exception(make_bot, monkeypatch, caplog):
    bot = make_bot(twitch_thank_in_chat=True)

    class FailingChannel:
        async def send_message(self, *, sender, message):
            raise http_error()

    monkeypatch.setattr(bot, "create_partialuser", lambda user_id: FailingChannel())
    with caplog.at_level(logging.WARNING, logger="twitch_bot"):
        await bot.event_subscription(sub_payload())
    assert "could not send chat thank-you" in caplog.text


async def test_clean_message_is_not_moderated(make_bot, monkeypatch, tmp_path):
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("xesque\n", encoding="utf-8")
    bot = make_bot(nsfw=NsfwFilter.from_path(wordlist))
    moderated = []
    monkeypatch.setattr(bot, "_moderate", RecordingCall())
    payload = SimpleNamespace(
        text="bom dia pessoal",
        chatter=SimpleNamespace(display_name="Ana", id="333"),
    )
    await bot.event_message(payload)
    assert bot._moderate.calls == []


async def test_flagged_message_is_moderated(make_bot, tmp_path):
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("xesque\n", encoding="utf-8")
    bot = make_bot(nsfw=NsfwFilter.from_path(wordlist))
    delete = RecordingCall()
    payload = SimpleNamespace(
        text="que xesque",
        id="msg-1",
        chatter=SimpleNamespace(display_name="Ana", id="333"),
        broadcaster=SimpleNamespace(
            delete_chat_messages=delete, timeout_user=RecordingCall()
        ),
    )
    await bot.event_message(payload)
    assert delete.calls == [{"moderator": BOT_ID, "message_id": "msg-1"}]


@pytest.mark.parametrize(
    ("delete_on", "timeout_seconds", "expect_delete", "expect_timeout"),
    [
        (True, 0, True, False),
        (False, 30, False, True),
        (True, 30, True, True),
        (False, 0, False, False),
    ],
)
async def test_moderate_matrix(
    make_bot, delete_on, timeout_seconds, expect_delete, expect_timeout
):
    bot = make_bot(
        nsfw_delete_message=delete_on, nsfw_timeout_seconds=timeout_seconds
    )
    delete = RecordingCall()
    timeout = RecordingCall()
    payload = SimpleNamespace(
        id="msg-1",
        chatter=SimpleNamespace(display_name="Ana", id="333"),
        broadcaster=SimpleNamespace(
            delete_chat_messages=delete, timeout_user=timeout
        ),
    )
    await bot._moderate(payload)
    assert (delete.calls == [{"moderator": BOT_ID, "message_id": "msg-1"}]) is (
        expect_delete
    )
    if expect_timeout:
        assert timeout.calls == [
            {
                "moderator": BOT_ID,
                "user": "333",
                "duration": timeout_seconds,
                "reason": "NSFW content",
            }
        ]
    else:
        assert timeout.calls == []


async def test_safe_moderation_swallows_http_exception(caplog):
    async def failing_action():
        raise http_error()

    with caplog.at_level(logging.WARNING, logger="twitch_bot"):
        await TwitchManager._safe_moderation(failing_action(), action_label="delete")
    assert "moderation failed (delete)" in caplog.text


async def test_safe_moderation_lets_other_errors_propagate():
    # Characterization: only twitchio.HTTPException is swallowed.
    async def failing_action():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await TwitchManager._safe_moderation(failing_action(), action_label="x")


async def test_setup_hook_registers_four_subscriptions(make_bot, monkeypatch):
    bot = make_bot()
    registered = []

    async def fake_subscribe(*, payload):
        registered.append(payload)

    monkeypatch.setattr(bot, "subscribe_websocket", fake_subscribe)
    await bot.setup_hook()
    assert len(registered) == 4
    for subscription in registered:
        assert subscription.condition["broadcaster_user_id"] == OWNER_ID
