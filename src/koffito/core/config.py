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
    to a client.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database -------------------------------------------------------------------------
    database_url: SecretStr = SecretStr("postgresql://koffito:koffito@localhost:5432/koffito")
    database_pool_size: int = 10

    # --- Our own auth ---------------------------------------------------------------------
    # HMAC key for access tokens (HS256). At least 32 random bytes: `python -c "import secrets;
    # print(secrets.token_urlsafe(48))"`. Rotating it signs everyone out.
    auth_jwt_secret: SecretStr
    auth_issuer: str = "koffito"
    auth_audience: str = "koffito-app"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    verify_email_ttl_hours: int = 24
    reset_password_ttl_minutes: int = 60
    jwt_leeway_seconds: int = 10
    # Failed logins before the account is locked, and for how long.
    login_max_failures: int = 10
    login_lockout_minutes: int = 15
    # Where links in emails point (the web app).
    app_base_url: str = "http://localhost:5173"
    # Path the refresh cookie is scoped to, as the browser sees it. The web app reaches the API
    # under /api (dev proxy / reverse proxy), so its auth routes are /api/auth/*.
    auth_cookie_path: str = "/api/auth"

    # --- Email (SMTP) ---------------------------------------------------------------------
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_use_tls: bool = False
    mail_from: str = "Koffito <no-reply@koffito.local>"

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
    # Auth endpoints per client IP; endpoints that send email also per email address.
    rate_limit_auth_limit: int = 20
    rate_limit_auth_window_seconds: int = 300
    rate_limit_email_limit: int = 5
    rate_limit_email_window_seconds: int = 3600

    # --- Background jobs ------------------------------------------------------------------
    jobs_enabled: bool = False
    jobs_interval_seconds: int = 300

    # --- Deployment -----------------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    enforce_https: bool = False
    trusted_hosts: Annotated[list[str], NoDecode] = ["*"]
    cors_origins: Annotated[list[str], NoDecode] = []
    log_level: str = "INFO"

    @field_validator("auth_jwt_secret")
    @classmethod
    def _strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("AUTH_JWT_SECRET must be at least 32 characters")
        return value

    @field_validator("app_base_url")
    @classmethod
    def _normalise_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("trusted_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_lists(cls, value: object) -> object:
        return _split_csv(value)

    @model_validator(mode="after")
    def _production_guard(self) -> Settings:
        if self.environment == "production":
            if not self.enforce_https:
                raise ValueError("ENFORCE_HTTPS must be true in production")
            if self.trusted_hosts == ["*"]:
                raise ValueError("TRUSTED_HOSTS must be explicit in production")
        return self

    @property
    def cookie_secure(self) -> bool:
        """Refresh cookies are `Secure` whenever the API is served over HTTPS."""
        return self.enforce_https


@lru_cache
def get_settings() -> Settings:
    return Settings()
