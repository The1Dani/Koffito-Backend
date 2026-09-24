import json
from datetime import UTC, datetime

import httpx
import pytest

from koffito.jobs.venues import choose_venue, run_venue_assignment
from koffito.supabase import SupabaseRest
from tests.support import SUPABASE_URL, FakeBackend

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def group(gid: str, size: int = 4) -> dict:
    return {
        "id": gid,
        "event_id": "e1",
        "venue_id": None,
        "events": {
            "event_at": "2026-09-26T10:00:00+00:00",
            "status": "matched",
            "target_group_size": size,
        },
    }


def venue(vid: str, name: str, capacity: int | None) -> dict:
    return {
        "id": vid,
        "name": name,
        "capacity": capacity,
        "latitude": None,
        "longitude": None,
        "popular_times": None,
    }


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


def test_choose_venue_prefers_the_largest_cafe_that_fits():
    venues = [venue("v1", "Tiny", 2), venue("v2", "Big", 12), venue("v3", "Mid", 6)]
    assert choose_venue(group("g1", 4), venues)["id"] == "v2"


def test_choose_venue_treats_unknown_capacity_as_fitting_but_after_known_ones():
    venues = [venue("v1", "Unknown", None), venue("v2", "Known", 6)]
    assert choose_venue(group("g1", 4), venues)["id"] == "v2"
    assert choose_venue(group("g1", 8), venues)["id"] == "v1"


def test_choose_venue_breaks_ties_by_name_and_gives_up_when_nothing_fits():
    venues = [venue("v2", "Beta", 6), venue("v1", "Alpha", 6)]
    assert choose_venue(group("g1", 4), venues)["id"] == "v1"
    assert choose_venue(group("g1", 10), venues) is None


async def test_run_venue_assignment_patches_only_groups_that_got_a_cafe(sb, backend):
    backend.on("GET", "/groups", httpx.Response(200, json=[group("g1", 4), group("g2", 20)]))
    backend.on("GET", "/venues", httpx.Response(200, json=[venue("v1", "Tucano", 8)]))
    backend.always("PATCH", "/groups", httpx.Response(204))

    stats = await run_venue_assignment(sb, now=NOW)

    assert (stats.groups_considered, stats.venues_assigned) == (2, 1)
    groups_query = backend.calls("GET", "/groups")[0].url.params
    assert groups_query.get_list("venue_id") == ["is.null"]
    assert groups_query.get_list("events.event_at") == ["gt.2026-09-25T12:00:00+00:00"]
    assert backend.calls("GET", "/venues")[0].url.params.get_list("is_active") == ["eq.true"]

    patches = backend.calls("PATCH", "/groups")
    assert [p.url.params.get_list("id") for p in patches] == [["eq.g1"]]
    assert json.loads(patches[0].content) == {"venue_id": "v1"}
    assert patches[0].headers["apikey"] == "sb_secret_test"
