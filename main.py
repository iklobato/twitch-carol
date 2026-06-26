from __future__ import annotations

import asyncio
import logging

import uvicorn

from config import Settings
from livepix import LivePixAlertService, LivePixClient
from nsfw import NsfwFilter
from overlay import OverlayHub
from twitch_bot import TwitchManager
from web import build_app

logger = logging.getLogger("twitch_live_manager")


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()

    hub = OverlayHub()
    nsfw = NsfwFilter.from_path(settings.nsfw_wordlist_path)

    async with LivePixClient(settings) as livepix:
        alerts = LivePixAlertService(livepix, hub)
        app = build_app(hub, alerts, settings)
        server = uvicorn.Server(
            uvicorn.Config(
                app, host=settings.host, port=settings.port, log_level="info"
            )
        )
        bot = TwitchManager(settings, hub, nsfw)
        logger.info("overlay: http://%s:%s/overlay", settings.host, settings.port)
        async with bot:
            await asyncio.gather(server.serve(), bot.start())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
