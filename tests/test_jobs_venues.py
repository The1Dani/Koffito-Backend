from datetime import UTC, datetime

from koffito.jobs.venues import choose_venue

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
