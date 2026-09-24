import json
from datetime import UTC, datetime

import httpx
import pytest

from koffito.jobs.matchmaking import plan_groups, run_matchmaking
from koffito.supabase import SupabaseRest
from tests.support import SUPABASE_URL, FakeBackend

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
EVENT = {
    "id": "e1",
    "event_at": "2026-09-26T10:00:00+00:00",
    "target_group_size": 2,
    "capacity": 40,
    "default_venue_id": None,
}


def people(n: int) -> list[dict]:
    return [
        {"id": f"p{i}", "user_id": f"u{i}", "joined_at": f"2026-09-20T00:00:0{i}"} for i in range(n)
    ]


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


def ids(groups: list[list[dict]]) -> list[list[str]]:
    return [[m["id"] for m in g] for g in groups]


def test_plan_groups_chunks_in_join_order():
    assert ids(plan_groups(people(8), 4)) == [["p0", "p1", "p2", "p3"], ["p4", "p5", "p6", "p7"]]


def test_plan_groups_keeps_a_remainder_of_two_or_more_as_its_own_group():
    assert ids(plan_groups(people(6), 4)) == [["p0", "p1", "p2", "p3"], ["p4", "p5"]]


def test_plan_groups_merges_a_leftover_single_into_the_previous_group():
    assert ids(plan_groups(people(5), 4)) == [["p0", "p1", "p2", "p3", "p4"]]


def test_plan_groups_leaves_a_lone_participant_unmatched():
    assert plan_groups(people(1), 4) == []
    assert plan_groups([], 4) == []


async def test_run_matchmaking_creates_groups_and_marks_participants_and_event(sb, backend):
    backend.on("GET", "/events", httpx.Response(200, json=[EVENT]))
    backend.on("GET", "/event_participants", httpx.Response(200, json=people(3)))
    backend.on("POST", "/groups", httpx.Response(201, json=[{"id": "g1"}]))
    backend.always("PATCH", "/event_participants", httpx.Response(204))
    backend.on("PATCH", "/events", httpx.Response(204))

    stats = await run_matchmaking(sb, now=NOW)

    assert (stats.events_considered, stats.groups_created, stats.participants_matched) == (1, 1, 3)

    events_query = backend.calls("GET", "/events")[0].url.params
    assert events_query.get_list("status") == ["eq.open"]
    assert events_query.get_list("event_at") == [
        "gt.2026-09-25T12:00:00+00:00",
        "lte.2026-09-26T14:00:00+00:00",
    ]

    participants_query = backend.calls("GET", "/event_participants")[0].url.params
    assert participants_query.get_list("event_id") == ["eq.e1"]
    assert participants_query.get_list("status") == ["eq.joined"]
    assert participants_query["order"] == "joined_at.asc"

    group_insert = backend.calls("POST", "/groups")[0]
    assert json.loads(group_insert.content) == {"event_id": "e1"}
    assert group_insert.headers["apikey"] == "sb_secret_test"

    match = backend.calls("PATCH", "/event_participants")[0]
    assert match.url.params.get_list("id") == ["in.(p0,p1,p2)"]
    assert json.loads(match.content) == {"group_id": "g1", "status": "matched"}

    event_patch = backend.calls("PATCH", "/events")[0]
    assert event_patch.url.params.get_list("id") == ["eq.e1"]
    assert json.loads(event_patch.content) == {"status": "matched"}


async def test_run_matchmaking_writes_nothing_for_a_lone_participant(sb, backend):
    backend.on("GET", "/events", httpx.Response(200, json=[EVENT]))
    backend.on("GET", "/event_participants", httpx.Response(200, json=people(1)))

    stats = await run_matchmaking(sb, now=NOW)

    assert (stats.events_considered, stats.groups_created) == (1, 0)
    assert backend.calls("POST", "/groups") == []
    assert backend.calls("PATCH", "/event_participants") == []
    assert backend.calls("PATCH", "/events") == []
