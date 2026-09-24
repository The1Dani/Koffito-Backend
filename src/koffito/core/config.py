from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Process configuration, read from the environment (and a local `.env` in development).

    Secrets are `SecretStr` so they never show up in logs or reprs. Nothing here is ever sent
    to a client; the app only needs the Supabase URL and the publishable key.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Supabase -------------------------------------------------------------------------
    supabase_url: str
    supabase_publishable_key: str
    # Only used by system jobs (matchmaking, reminders). Never for user requests.
    supabase_service_role_key: SecretStr | None = None
    # Plaintext from `select private.rotate_backend_key();` — the Data API gate.
    koffito_backend_key: SecretStr

    # --- JWT verification -----------------------------------------------------------------
    jwt_audience: str = "authenticated"
    jwt_leeway_seconds: int = 10
    jwks_cache_ttl_seconds: int = 3600
    jwks_min_refetch_seconds: int = 60
    # Slightly above the `authenticated` role's statement_timeout (8s) on the database.
    supabase_timeout_seconds: float = 10.0

    # --- Rate limiting (per user, per process) --------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_read_limit: int = 120
    rate_limit_read_window_seconds: int = 60
    rate_limit_write_limit: int = 30
    rate_limit_write_window_seconds: int = 60
    rate_limit_report_limit: int = 5
    rate_limit_report_window_seconds: int = 3600
    rate_limit_admin_limit: int = 60
    rate_limit_admin_window_seconds: int = 60

    # --- Background jobs ------------------------------------------------------------------
    jobs_enabled: bool = False
    jobs_interval_seconds: int = 300

    # --- Deployment -----------------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    enforce_https: bool = False
    trusted_hosts: Annotated[list[str], NoDecode] = ["*"]
    cors_origins: Annotated[list[str], NoDecode] = []
    log_level: str = "INFO"

    @field_validator("supabase_url")
    @classmethod
    def _normalise_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("https://", "http://")):
            raise ValueError("supabase_url must start with https:// (or http:// for local dev)")
        return value

    @field_validator("trusted_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_lists(cls, value: object) -> object:
        return _split_csv(value)

    @model_validator(mode="after")
    def _production_guard(self) -> "Settings":
        if self.environment == "production":
            if not self.enforce_https:
                raise ValueError("ENFORCE_HTTPS must be true in production")
            if self.trusted_hosts == ["*"]:
                raise ValueError("TRUSTED_HOSTS must be explicit in production")
        return self

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def rest_url(self) -> str:
        return f"{self.supabase_url}/rest/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
