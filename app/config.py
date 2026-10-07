from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_environment: str = "development"

    llm_provider: str = "openai"
    llm_model: str = "gpt-5-mini"

    llm_api_key: str | None = Field(
        default=None,
        repr=False,
    )

    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings()