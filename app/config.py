from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YTM_")

    language: str = "en"
    location: str = ""
    timeout_seconds: float = 10.0
    max_concurrency: int = 8
    ready_cache_seconds: float = 60.0
    log_level: str = "INFO"

    # Dormant fallbacks: unset by default. Setting either is a redeploy, not a code change.
    proxy_url: str | None = None
    auth_file: str | None = None


settings = Settings()
