from __future__ import annotations

import logging
from typing import Awaitable

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from alerts import AlertKind, StreamAlert, tier_label
from config import Settings
from nsfw import NsfwFilter
from overlay import OverlayHub

logger = logging.getLogger(__name__)


class TwitchManager(commands.Bot):
    def __init__(self, settings: Settings, hub: OverlayHub, nsfw: NsfwFilter) -> None:
        super().__init__(
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
            bot_id=settings.twitch_bot_id,
            owner_id=settings.twitch_owner_id,
            prefix=settings.twitch_prefix,
        )
        self._settings = settings
        self._hub = hub
        self._nsfw = nsfw

    async def setup_hook(self) -> None:
        channel = self._settings.twitch_owner_id
        subscriptions = [
            eventsub.ChatMessageSubscription(
                broadcaster_user_id=channel, user_id=self.bot_id
            ),
            eventsub.ChannelSubscribeSubscription(broadcaster_user_id=channel),
            eventsub.ChannelSubscribeMessageSubscription(broadcaster_user_id=channel),
            eventsub.ChannelSubscriptionGiftSubscription(broadcaster_user_id=channel),
        ]
        for subscription in subscriptions:
            await self.subscribe_websocket(payload=subscription)

    async def event_ready(self) -> None:
        logger.info("twitch bot ready as user id %s", self.bot_id)

    async def event_subscription(self, payload: twitchio.ChannelSubscribe) -> None:
        if payload.gift:
            return
        await self._announce(
            StreamAlert(
                kind=AlertKind.SUBSCRIPTION,
                headline=f"{payload.user.display_name} assinou!",
                detail=f"Nova assinatura {tier_label(payload.tier)}",
                username=payload.user.display_name,
            )
        )

    async def event_subscription_message(
        self, payload: twitchio.ChannelSubscriptionMessage
    ) -> None:
        await self._announce(
            StreamAlert(
                kind=AlertKind.RESUB,
                headline=f"{payload.user.display_name} renovou!",
                detail=f"{payload.cumulative_months} meses - {payload.message.text or ''}".strip(),
                username=payload.user.display_name,
            )
        )

    async def event_subscription_gift(
        self, payload: twitchio.ChannelSubscriptionGift
    ) -> None:
        gifter = (
            "Anonimo"
            if payload.anonymous or payload.user is None
            else payload.user.display_name
        )
        await self._announce(
            StreamAlert(
                kind=AlertKind.GIFT,
                headline=f"{gifter} presenteou {payload.total} sub(s)!",
                detail=f"{tier_label(payload.tier)} gift",
                username=gifter,
            )
        )

    async def _announce(self, alert: StreamAlert) -> None:
        await self._hub.broadcast(alert)
        if self._settings.twitch_thank_in_chat:
            await self._thank_in_chat(alert)

    async def _thank_in_chat(self, alert: StreamAlert) -> None:
        try:
            channel = self.create_partialuser(self._settings.twitch_owner_id)
            await channel.send_message(sender=self.bot_id, message=alert.headline)
        except twitchio.HTTPException as error:
            logger.warning("could not send chat thank-you: %s", error)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        if not self._nsfw.is_flagged(payload.text):
            return
        logger.warning(
            "NSFW chat flagged from %s: %r", payload.chatter.display_name, payload.text
        )
        await self._moderate(payload)

    async def _moderate(self, payload: twitchio.ChatMessage) -> None:
        broadcaster = payload.broadcaster
        if self._settings.nsfw_delete_message:
            await self._safe_moderation(
                broadcaster.delete_chat_messages(
                    moderator=self.bot_id, message_id=payload.id
                ),
                action_label="delete message",
            )
        if self._settings.nsfw_timeout_seconds > 0:
            await self._safe_moderation(
                broadcaster.timeout_user(
                    moderator=self.bot_id,
                    user=payload.chatter.id,
                    duration=self._settings.nsfw_timeout_seconds,
                    reason="NSFW content",
                ),
                action_label="timeout user",
            )

    @staticmethod
    async def _safe_moderation(
        action: Awaitable[object], *, action_label: str = ""
    ) -> None:
        try:
            await action
        except twitchio.HTTPException as error:
            logger.warning("moderation failed (%s): %s", action_label, error)
