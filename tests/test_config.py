import pytest
from pydantic import ValidationError

from koffito.core.config import Settings

BASE = {"auth_jwt_secret": "s" * 40}


def test_defaults_are_safe_for_development():
    s = Settings(**BASE, _env_file=None)
    assert s.environment == "development"
    assert s.enforce_https is False
    assert s.cookie_secure is False
    assert s.jobs_enabled is False
    assert s.rate_limit_enabled is True
    assert s.access_token_ttl_minutes == 15


def test_secret_values_do_not_leak_in_repr():
    s = Settings(**BASE, smtp_password="mail-secret", _env_file=None)
    assert "s" * 40 not in repr(s)
    assert "mail-secret" not in repr(s)
    assert "koffito:koffito" not in repr(s)  # database password


def test_jwt_secret_must_be_long():
    with pytest.raises(ValidationError):
        Settings(auth_jwt_secret="short", _env_file=None)


def test_missing_jwt_secret_fails_fast():
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_list_settings_split_on_commas():
    s = Settings(
        **BASE,
        cors_origins="https://a.app, https://b.app",
        trusted_hosts="api.koffito.app",
        _env_file=None,
    )
    assert s.cors_origins == ["https://a.app", "https://b.app"]
    assert s.trusted_hosts == ["api.koffito.app"]


def test_production_requires_https_and_explicit_hosts():
    with pytest.raises(ValidationError):
        Settings(**BASE, environment="production", _env_file=None)
    s = Settings(
        **BASE,
        environment="production",
        enforce_https=True,
        trusted_hosts="api.koffito.app",
        _env_file=None,
    )
    assert s.cookie_secure is True


def test_app_base_url_loses_trailing_slash():
    assert Settings(**BASE, app_base_url="https://koffito.app/", _env_file=None).app_base_url == (
        "https://koffito.app"
    )
