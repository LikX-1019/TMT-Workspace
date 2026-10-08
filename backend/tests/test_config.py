"""Configuration and secret policy tests."""

import pytest
from app.core.config import Environment, Settings
from pydantic import ValidationError


def load_settings(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> Settings:
    """Load settings from explicit TMT_ environment variables only."""

    relevant_names = [
        "TMT_ENVIRONMENT",
        "TMT_DEBUG",
        "TMT_DATABASE_URL",
        "TMT_REDIS_URL",
        "TMT_SECRET_KEY",
    ]
    for name in relevant_names:
        monkeypatch.delenv(name, raising=False)

    for name, value in values.items():
        monkeypatch.setenv(name, value)

    return Settings(_env_file=None)


def test_tmt_environment_variables_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(
        monkeypatch,
        {
            "TMT_ENVIRONMENT": "testing",
            "TMT_DATABASE_URL": "postgresql+asyncpg://config-user:config-pass@db:5432/config-db",
            "TMT_REDIS_URL": "redis://config-redis:6380/9",
            "TMT_SECRET_KEY": "configured-local-secret",
        },
    )

    assert settings.environment == "testing"
    assert settings.database_url == "postgresql+asyncpg://config-user:config-pass@db:5432/config-db"
    assert settings.redis_url == "redis://config-redis:6380/9"
    assert settings.secret_key.get_secret_value() == "configured-local-secret"


@pytest.mark.parametrize("environment", ["local", "testing"])
def test_local_and_testing_allow_secret_fallback(
    monkeypatch: pytest.MonkeyPatch,
    environment: Environment,
) -> None:
    settings = load_settings(monkeypatch, {"TMT_ENVIRONMENT": environment})

    assert settings.requires_explicit_secret is False
    assert settings.secret_key.get_secret_value() == "local-or-testing-only-secret"


def test_development_requires_explicit_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="TMT_SECRET_KEY"):
        load_settings(monkeypatch, {"TMT_ENVIRONMENT": "development"})


def test_production_requires_explicit_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="TMT_SECRET_KEY"):
        load_settings(monkeypatch, {"TMT_ENVIRONMENT": "production"})


@pytest.mark.parametrize("environment", ["development", "production"])
def test_development_and_production_accept_explicit_secret(
    monkeypatch: pytest.MonkeyPatch,
    environment: Environment,
) -> None:
    settings = load_settings(
        monkeypatch,
        {
            "TMT_ENVIRONMENT": environment,
            "TMT_SECRET_KEY": "explicit-deployment-secret",
        },
    )

    assert settings.requires_explicit_secret is True
    assert settings.secret_key.get_secret_value() == "explicit-deployment-secret"


def test_rejected_placeholders_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="TMT_SECRET_KEY"):
        load_settings(
            monkeypatch,
            {
                "TMT_ENVIRONMENT": "development",
                "TMT_SECRET_KEY": "change-me-in-local-only",
            },
        )


def test_authentication_settings_have_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(monkeypatch, {"TMT_ENVIRONMENT": "testing"})

    assert settings.access_token_ttl_minutes == 30
    assert settings.refresh_token_ttl_days == 14
    assert settings.refresh_cookie_name == "tmt_refresh_token"
    assert settings.refresh_cookie_path == "/api/v1/auth"
    assert settings.refresh_cookie_samesite == "lax"
    assert settings.refresh_cookie_secure is False
    assert settings.login_max_attempts == 10
    assert settings.login_window_seconds == 300
    assert settings.access_token_ttl_seconds == 1800


def test_throttle_settings_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        monkeypatch,
        {
            "TMT_ENVIRONMENT": "testing",
            "TMT_LOGIN_MAX_ATTEMPTS": "5",
            "TMT_LOGIN_WINDOW_SECONDS": "60",
            "TMT_ACCESS_TOKEN_TTL_MINUTES": "15",
        },
    )

    assert settings.login_max_attempts == 5
    assert settings.login_window_seconds == 60
    assert settings.access_token_ttl_seconds == 900


@pytest.mark.parametrize("environment", ["local", "development", "testing"])
def test_non_production_allows_insecure_refresh_cookie(
    monkeypatch: pytest.MonkeyPatch, environment: Environment
) -> None:
    settings = load_settings(
        monkeypatch,
        {
            "TMT_ENVIRONMENT": environment,
            "TMT_SECRET_KEY": "explicit-deployment-secret",
        },
    )

    assert settings.refresh_cookie_secure is False


def test_production_forces_secure_refresh_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        monkeypatch,
        {
            "TMT_ENVIRONMENT": "production",
            "TMT_SECRET_KEY": "explicit-deployment-secret",
            "TMT_REFRESH_COOKIE_SECURE": "false",
        },
    )

    assert settings.refresh_cookie_secure is True
