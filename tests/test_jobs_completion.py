import json
from datetime import UTC, datetime

import httpx
import pytest

from koffito.jobs.completion import run_completion
from koffito.supabase import SupabaseRest
from tests.support import SUPABASE_URL, FakeBackend

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def sb(backend: FakeBackend) -> SupabaseRest:
    http = httpx.AsyncClient(transport=httpx.MockTransport(backend))
    return SupabaseRest(
        http,
        rest_url=f"{SUPABASE_URL}/rest/v1",
        publishable_key="pub-key",
        service_key="sb_secret_test",
        backend_key="backend-key",
    )


async def test_completes_active_events_that_ended_two_hours_ago(sb, backend):
    backend.on("PATCH", "/events", httpx.Response(200, json=[{"id": "e1"}, {"id": "e2"}]))

    stats = await run_completion(sb, now=NOW)

    assert stats.events_completed == 2
    patch = backend.calls("PATCH", "/events")[0]
    p = patch.url.params
    assert p.get_list("status") == ["in.(open,matched,confirmed)"]
    assert p.get_list("event_at") == ["lte.2026-09-25T10:00:00+00:00"]
    assert p["select"] == "id"
    assert json.loads(patch.content) == {"status": "completed"}
    assert patch.headers["apikey"] == "sb_secret_test"  # service role, never a user token
    assert "authorization" not in patch.headers


async def test_nothing_to_complete(sb, backend):
    backend.on("PATCH", "/events", httpx.Response(200, json=[]))

    stats = await run_completion(sb, now=NOW)

    assert stats.events_completed == 0
