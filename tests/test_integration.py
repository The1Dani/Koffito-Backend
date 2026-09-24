"""Live checks against the real Supabase project. Opt in with:

    KOFFITO_INTEGRATION=1 KOFFITO_TEST_EMAIL=... KOFFITO_TEST_PASSWORD=... uv run pytest tests/test_integration.py

`.env` must hold SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and KOFFITO_BACKEND_KEY.
"""

import os
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from koffito.core.config import Settings
from koffito.main import create_app
from koffito.supabase.errors import GATE_MESSAGE_PREFIX

pytestmark = pytest.mark.skipif(
    os.environ.get("KOFFITO_INTEGRATION") != "1",
    reason="set KOFFITO_INTEGRATION=1 (and KOFFITO_TEST_EMAIL / KOFFITO_TEST_PASSWORD)",
)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(rate_limit_enabled=False)


@pytest.fixture(scope="module")
def live_token(settings: Settings) -> str:
    response = httpx.post(
        f"{settings.supabase_url}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": settings.supabase_publishable_key},
        json={
            "email": os.environ["KOFFITO_TEST_EMAIL"],
            "password": os.environ["KOFFITO_TEST_PASSWORD"],
        },
        timeout=20,
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def live(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def test_unauthenticated_request_is_401(live: TestClient):
    r = live.get("/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_token"


def test_me_and_open_events_with_a_real_token(live: TestClient, live_token: str):
    headers = {"authorization": f"Bearer {live_token}"}
    me = live.get("/me", headers=headers)
    assert me.status_code == 200, me.text
    assert "isAdmin" in me.json()
    events = live.get("/events", headers=headers)
    assert events.status_code == 200, events.text
    assert isinstance(events.json(), list)


def test_direct_data_api_access_is_gated(settings: Settings, live_token: str):
    """The same user token straight at PostgREST, without the backend key, is refused."""
    r = httpx.post(
        f"{settings.rest_url}/rpc/get_me",
        headers={
            "apikey": settings.supabase_publishable_key,
            "authorization": f"Bearer {live_token}",
        },
        json={},
        timeout=20,
    )
    assert r.status_code in (401, 403), r.text
    assert r.json()["message"].startswith(GATE_MESSAGE_PREFIX)
