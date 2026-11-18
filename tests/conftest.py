"""Tests run against a real Postgres (the one from `docker compose up -d db`).

A throwaway database `koffito_test` is created once per session from db/migrations, and every
table is emptied before each test. Emails are captured in memory instead of sent.
Set TEST_DATABASE_URL to point somewhere else; without a reachable server the DB tests skip.
"""

import asyncio
import os
import re
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from koffito.auth.mailer import Mail
from koffito.core.config import Settings
from koffito.main import create_app
from koffito.migrate import migrate

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://koffito:koffito@localhost:5432/postgres"
)
TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://koffito:koffito@localhost:5432/koffito_test"
)
SECRET = "test-secret-" + "x" * 40

TABLES = (
    "event_ratings, reports, event_participants, groups, events, venues, surveys, "
    "profile_languages, user_settings, profiles, email_tokens, refresh_tokens, users"
)


def make_settings(**overrides) -> Settings:
    values = {
        "database_url": TEST_DSN,
        "auth_jwt_secret": SECRET,
        "rate_limit_enabled": False,
        "app_base_url": "http://app.test",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def database() -> str:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3) as conn:
            conn.execute("drop database if exists koffito_test with (force)")
            conn.execute("create database koffito_test")
    except psycopg.OperationalError as exc:
        pytest.skip(f"no test Postgres ({exc}); run `docker compose up -d db`")
    migrate(TEST_DSN)
    return TEST_DSN


@pytest.fixture
def clean_db(database: str) -> str:
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(f"truncate {TABLES} cascade")
    return database


class Outbox:
    def __init__(self) -> None:
        self.mails: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.mails.append(mail)

    def token(self, to: str, path: str) -> str:
        for mail in reversed(self.mails):
            if mail.to == to and f"/{path}?token=" in mail.link:
                return re.search(r"token=([\w-]+)", mail.link).group(1)  # type: ignore[union-attr]
        raise AssertionError(f"no {path} email for {to}")


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def outbox() -> Outbox:
    return Outbox()


@pytest.fixture
def client(clean_db: str, settings: Settings, outbox: Outbox) -> Iterator[TestClient]:
    app = create_app(settings)
    with make_client(app) as client:
        app.state.mailer.send = outbox.send  # capture instead of SMTP
        yield client


def make_client(app) -> TestClient:
    # psycopg's async driver needs a selector event loop (Windows defaults to Proactor).
    return TestClient(
        app,
        headers={"X-Requested-With": "koffito"},
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    )


@pytest.fixture
def event_loop_policy():
    """pytest-asyncio: run async tests on a selector loop too."""
    if os.name == "nt":
        return asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
    return asyncio.DefaultEventLoopPolicy()


def signup(
    client: TestClient,
    outbox: Outbox,
    email: str,
    *,
    name: str = "Ana",
    password: str = "Cortado-and-croissant",
) -> dict[str, str]:
    """Register + confirm the email; returns auth headers for that user."""
    assert (
        client.post(
            "/auth/register", json={"email": email, "password": password, "first_name": name}
        ).status_code
        == 202
    )
    r = client.post("/auth/verify-email", json={"token": outbox.token(email, "verify-email")})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def sql(dsn: str, query: str, params: list | None = None) -> list[tuple]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, params or [])  # type: ignore[arg-type]
        return cur.fetchall() if cur.description else []
