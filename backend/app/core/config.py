"""Application settings loaded from environment variables."""

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "development", "testing", "production"]


class Settings(BaseSettings):
    """Strongly typed application configuration.

    All settings use the ``TMT_`` prefix so application configuration is easy to
    identify in process listings and deployment manifests.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "local"
    debug: bool = False
    project_name: str = "TMT Workspace"

    database_url: str = Field(
        default="postgresql+asyncpg://tmt:tmt_change_me@localhost:5432/app",
        examples=["postgresql+asyncpg://user:password@localhost:5432/app"],
    )
    db_echo: bool = False
    sql_timeout_seconds: int = 30

    redis_url: str = "redis://localhost:6379/0"

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    secret_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(32)))
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    jwt_algorithm: Literal["HS256"] = "HS256"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.is_production and self.secret_key.get_secret_value() in {
            "",
            "change-me-in-local-only",
        }:
            raise ValueError("TMT_SECRET_KEY must be configured in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    settings = Settings()
    if settings.environment == "local":
        # Keep a permissive developer experience without weakening other environments.
        TypeAdapter(list[str]).validate_python(settings.cors_origins)
    return settings
