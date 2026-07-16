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
    # Remote OpenAI-compatible inference (DO Gradient, OpenRouter, OpenAI, Groq...),
    # used when llm_backend == "openai". No local model.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    # OpenRouter only: force routing to a provider that honors every requested
    # param (so response_format json mode is actually applied). No-op elsewhere.
    llm_require_provider_params: bool = False
    llm_max_input_tokens: int = 30000
    llm_max_output_tokens: int = 3000
    # PgBouncer in transaction mode can't keep server-side prepared statements;
    # set this true when database_url points at a pooled endpoint.
    db_disable_prepared_statements: bool = False
    simulation: bool = False
    # Comma-separated Twitch logins allowed to impersonate other channels.
    admin_logins: str = ""
    # Fallback audio store when Spaces is not configured (dev/simulation).
    audio_local_dir: str = "/data/audio"
    # How long raw recordings live in Spaces. Long by default: capture is
    # decoupled from processing (a throttled pool of N transcribe workers drains
    # the backlog over time), so audio must outlive the backlog and stay
    # available for re-processing. Transcript/analysis output is already durable
    # in Postgres; this is the knob that trades storage cost for backlog depth.
    audio_retention_days: int = 365
    # Sentry error reporting. Empty DSN disables it (dev/tests never send).
    sentry_dsn: str = ""
    sentry_environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
