import pytest
from pydantic import ValidationError

from koffito.core.config import Settings

BASE = {
    "supabase_url": "https://proj.supabase.co/",
    "supabase_publishable_key": "sb_publishable_x",
    "koffito_backend_key": "backend-secret",
}


def test_derived_supabase_urls_strip_trailing_slash():
    s = Settings(**BASE, _env_file=None)
    assert s.supabase_url == "https://proj.supabase.co"
    assert s.jwt_issuer == "https://proj.supabase.co/auth/v1"
    assert s.jwks_url == "https://proj.supabase.co/auth/v1/.well-known/jwks.json"
    assert s.rest_url == "https://proj.supabase.co/rest/v1"


def test_defaults_are_safe_for_development():
    s = Settings(**BASE, _env_file=None)
    assert s.jwt_audience == "authenticated"
    assert s.environment == "development"
    assert s.enforce_https is False
    assert s.jobs_enabled is False
    assert s.rate_limit_enabled is True
    assert s.supabase_service_role_key is None


def test_secret_values_do_not_leak_in_repr():
    s = Settings(**BASE, supabase_service_role_key="svc-secret", _env_file=None)
    assert "backend-secret" not in repr(s)
    assert "svc-secret" not in repr(s)
    assert s.koffito_backend_key.get_secret_value() == "backend-secret"


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
    assert s.trusted_hosts == ["api.koffito.app"]


def test_missing_required_setting_fails_fast():
    with pytest.raises(ValidationError):
        Settings(supabase_url="https://proj.supabase.co", _env_file=None)
