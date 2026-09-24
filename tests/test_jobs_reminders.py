import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from koffito.jobs.notifier import Notifier
from koffito.jobs.reminders import run_reminders
from koffito.jobs.runner import JOBS, run_job
from koffito.supabase import SupabaseRest
from tests.support import SUPABASE_URL, FakeBackend

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
U1 = uuid.UUID("11111111-1111-4111-8111-111111111111")
U2 = uuid.UUID("44444444-4444-4444-8444-444444444444")
EVENT = {
    "id": "22222222-2222-4222-8222-222222222222",
    "title": None,
    "event_at": "2026-09-26T06:00:00+00:00",
    "status": "matched",
}


def participant(pid: str, user: uuid.UUID, status: str) -> dict[str, Any]:
    return {
        "id": pid,
        "user_id": str(user),
        "event_id": EVENT["id"],
        "status": status,
        "events": EVENT,
        "profiles": {"display_name": "x", "user_settings": {"reminders_enabled": True}},
    }


class RecordingNotifier(Notifier):
    def __init__(self, fail_for: set[uuid.UUID] | None = None) -> None:
        self.sent: list[tuple[uuid.UUID, str, Mapping[str, Any]]] = []
        self.fail_for = fail_for or set()

    async def send(self, user_id: uuid.UUID, kind: str, payload: Mapping[str, Any]) -> None:
        if user_id in self.fail_for:
            raise RuntimeError("push provider down")
        self.sent.append((user_id, kind, payload))


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


async def test_24h_pass_queries_due_participants_notifies_and_stamps(sb, backend):
    backend.on(
        "GET", "/event_participants", httpx.Response(200, json=[participant("p1", U1, "matched")])
    )
    backend.on("GET", "/event_participants", httpx.Response(200, json=[]))  # 3h pass
    backend.on("PATCH", "/event_participants", httpx.Response(204))
    notifier = RecordingNotifier()

    stats = await run_reminders(sb, notifier, now=NOW)

    assert (stats.sent_24h, stats.sent_3h, stats.failed) == (1, 0, 0)
    assert notifier.sent == [
        (
            U1,
            "reminder_24h",
            {"event_id": EVENT["id"], "event_at": EVENT["event_at"], "title": None},
        )
    ]
    query = backend.calls("GET", "/event_participants")[0]
    p = query.url.params
    assert "events!inner(" in p["select"]
    assert "user_settings!inner(reminders_enabled)" in p["select"]
    assert p.get_list("status") == ["in.(joined,matched)"]
    assert p.get_list("reminded_24h_at") == ["is.null"]
    assert p.get_list("events.status") == ["in.(open,matched,confirmed)"]
    assert p.get_list("events.event_at") == [
        "gte.2026-09-25T12:00:00+00:00",
        "lte.2026-09-26T12:00:00+00:00",
    ]
    assert p.get_list("profiles.user_settings.reminders_enabled") == ["eq.true"]
    # service role, never a user token
    assert query.headers["apikey"] == "sb_secret_test"
    assert "authorization" not in query.headers
    stamp = backend.calls("PATCH", "/event_participants")[0]
    assert stamp.url.params.get_list("id") == ["eq.p1"]
    assert stamp.url.params.get_list("reminded_24h_at") == ["is.null"]  # idempotent across runners
    assert json.loads(stamp.content) == {"reminded_24h_at": "2026-09-25T12:00:00+00:00"}
    assert stamp.headers["prefer"] == "return=minimal"


async def test_3h_pass_includes_confirmed_24h_and_uses_a_3h_window(sb, backend):
    backend.on("GET", "/event_participants", httpx.Response(200, json=[]))  # 24h pass
    backend.on(
        "GET",
        "/event_participants",
        httpx.Response(200, json=[participant("p2", U2, "confirmed_24h")]),
    )
    backend.on("PATCH", "/event_participants", httpx.Response(204))
    notifier = RecordingNotifier()

    stats = await run_reminders(sb, notifier, now=NOW)

    assert (stats.sent_24h, stats.sent_3h) == (0, 1)
    assert notifier.sent[0][1] == "reminder_3h"
    p = backend.calls("GET", "/event_participants")[1].url.params
    assert p.get_list("status") == ["in.(joined,matched,confirmed_24h)"]
    assert p.get_list("reminded_3h_at") == ["is.null"]
    assert p.get_list("events.event_at") == [
        "gte.2026-09-25T12:00:00+00:00",
        "lte.2026-09-25T15:00:00+00:00",
    ]
    stamp = backend.calls("PATCH", "/event_participants")[0]
    assert stamp.url.params.get_list("reminded_3h_at") == ["is.null"]
    assert json.loads(stamp.content) == {"reminded_3h_at": "2026-09-25T12:00:00+00:00"}


async def test_notify_failure_leaves_the_row_for_the_next_run(sb, backend):
    rows = [participant("p1", U1, "joined"), participant("p2", U2, "joined")]
    backend.on("GET", "/event_participants", httpx.Response(200, json=rows))
    backend.on("GET", "/event_participants", httpx.Response(200, json=[]))
    backend.always("PATCH", "/event_participants", httpx.Response(204))
    notifier = RecordingNotifier(fail_for={U1})

    stats = await run_reminders(sb, notifier, now=NOW)

    assert (stats.sent_24h, stats.failed) == (1, 1)
    stamps = backend.calls("PATCH", "/event_participants")
    assert [s.url.params.get_list("id") for s in stamps] == [["eq.p2"]]


async def test_job_registry_and_one_shot_runner(sb, backend):
    assert set(JOBS) == {"reminders", "matchmaking", "venues"}
    notifier = RecordingNotifier()
    # nothing due anywhere: every job completes against an empty backend
    for name in JOBS:
        await run_job(name, sb, notifier)
    assert notifier.sent == []


async def test_stamp_failure_is_counted_and_does_not_abort_the_run(sb, backend):
    rows = [participant("p1", U1, "joined"), participant("p2", U2, "joined")]
    backend.on("GET", "/event_participants", httpx.Response(200, json=rows))
    backend.on("GET", "/event_participants", httpx.Response(200, json=[]))  # 3h pass must still run
    backend.on("PATCH", "/event_participants", httpx.Response(500, text="boom"))
    backend.on("PATCH", "/event_participants", httpx.Response(204))
    notifier = RecordingNotifier()

    stats = await run_reminders(sb, notifier, now=NOW)

    assert (stats.sent_24h, stats.failed) == (1, 1)
    assert len(notifier.sent) == 2
    assert len(backend.calls("GET", "/event_participants")) == 2
