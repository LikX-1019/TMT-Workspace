"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "development", "testing", "production"]


class Settings(BaseSettings):
    """Strongly typed application configuration.

    All settings use the ``TMT_`` prefix so application configuration is easy to
    identify in process listings and deployment manifests.
    """

    model_config = SettingsConfigDict(
        env_prefix="TMT_",
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

    secret_key: SecretStr = Field(default=SecretStr("local-or-testing-only-secret"))
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    jwt_algorithm: Literal["HS256"] = "HS256"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def requires_explicit_secret(self) -> bool:
        """Report whether deployment policy forbids the development fallback."""

        return self.environment in {"development", "production"}

    @model_validator(mode="after")
    def validate_explicit_secret(self) -> "Settings":
        if self.requires_explicit_secret and self.secret_key.get_secret_value() in {
            "",
            "change-me-in-local-only",
            "local-or-testing-only-secret",
        }:
            raise ValueError(
                "TMT_SECRET_KEY must be explicitly configured for development/production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
