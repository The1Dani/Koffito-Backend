from datetime import UTC, datetime

from koffito.jobs.matchmaking import plan_groups

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
