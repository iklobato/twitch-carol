from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed app config. Env var names match the field names, case-insensitive."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    twitch_eventsub_secret: str = ""
    # Dev default is the Caddy entrypoint from docker compose.
    public_base_url: str = "http://localhost:8080"
    # Host-mapped compose ports (5433/6380: 5432/6379 are taken by another
    # local project). Containers override both via compose environment.
    database_url: str = "postgresql+psycopg://app:app@localhost:5433/app"
    valkey_url: str = "redis://localhost:6380/0"
    spaces_endpoint: str = ""
    spaces_region: str = ""
    spaces_key: str = ""
    spaces_secret: str = ""
    spaces_bucket: str = ""
    fernet_key: str = ""
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    llm_backend: str = "local"
    llm_gguf_path: str = ""
    llm_max_input_tokens: int = 30000
    llm_max_output_tokens: int = 3000
    simulation: bool = False
    # Fallback audio store when Spaces is not configured (dev/simulation).
    audio_local_dir: str = "/data/audio"


@lru_cache
def get_settings() -> Settings:
    return Settings()
