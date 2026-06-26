from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    twitch_client_id: str
    twitch_client_secret: str
    twitch_bot_id: str
    twitch_owner_id: str
    twitch_prefix: str = "!"
    twitch_thank_in_chat: bool = False

    livepix_client_id: str
    livepix_client_secret: str
    livepix_webhook_secret: str

    host: str = "127.0.0.1"
    port: int = 8080

    nsfw_wordlist_path: Path = Path("nsfw_words_pt.txt")
    nsfw_delete_message: bool = True
    nsfw_timeout_seconds: int = 0
