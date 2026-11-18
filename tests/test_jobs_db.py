"""Background jobs against the real database."""

from datetime import UTC, datetime, timedelta

from koffito.db import Database
from koffito.jobs.completion import run_completion
from koffito.jobs.matchmaking import run_matchmaking
from koffito.jobs.reminders import run_reminders
from koffito.jobs.venues import run_venue_assignment
from tests.conftest import sql


def add_users(dsn, n):
    ids = []
    for i in range(n):
        ((uid,),) = sql(
            dsn,
            "insert into users (email, password_hash) values (%s, 'x') returning id",
            [f"u{i}@example.com"],
        )
        sql(dsn, "insert into profiles (id, display_name) values (%s, %s)", [uid, f"U{i}"])
        sql(dsn, "insert into user_settings (user_id) values (%s)", [uid])
        ids.append(uid)
    return ids


def add_event(dsn, *, hours_from_now, status="open", size=2):
    event_at = datetime.now(UTC) + timedelta(hours=hours_from_now)
    ((eid,),) = sql(
        dsn,
        "insert into events (event_at, status, target_group_size) values (%s, %s, %s) returning id",
        [event_at, status, size],
    )
    return eid


async def open_db(dsn) -> Database:
    db = Database(dsn, max_size=2)
    await db.open()
    return db


async def test_matchmaking_groups_joined_people_and_marks_the_event(clean_db):
    users = add_users(clean_db, 4)
    event = add_event(clean_db, hours_from_now=10, size=2)
    for u in users:
        sql(
            clean_db,
            "insert into event_participants (event_id, user_id) values (%s, %s)",
            [event, u],
        )
    db = await open_db(clean_db)
    try:
        stats = await run_matchmaking(db)
    finally:
        await db.close()
    assert stats.groups_created == 2 and stats.participants_matched == 4
    assert sql(clean_db, "select status::text from events") == [("matched",)]
    assert sql(
        clean_db, "select count(distinct group_id), min(status::text) from event_participants"
    ) == [(2, "matched")]


async def test_venue_assignment_gives_groups_a_cafe(clean_db):
    event = add_event(clean_db, hours_from_now=10)
    sql(clean_db, "insert into venues (name, address, capacity) values ('Naringi', 'x', 10)")
    sql(clean_db, "insert into groups (event_id) values (%s)", [event])
    db = await open_db(clean_db)
    try:
        stats = await run_venue_assignment(db)
    finally:
        await db.close()
    assert stats.venues_assigned == 1
    assert sql(clean_db, "select count(*) from groups where venue_id is not null") == [(1,)]


async def test_reminders_notify_once_and_respect_settings(clean_db):
    ana, bob = add_users(clean_db, 2)
    sql(clean_db, "update user_settings set reminders_enabled = false where user_id = %s", [bob])
    event = add_event(clean_db, hours_from_now=20)
    for u in (ana, bob):
        sql(
            clean_db,
            "insert into event_participants (event_id, user_id) values (%s, %s)",
            [event, u],
        )

    sent = []

    class Notifier:
        async def send(self, user_id, kind, payload):
            sent.append((str(user_id), kind))

    db = await open_db(clean_db)
    try:
        first = await run_reminders(db, Notifier())
        second = await run_reminders(db, Notifier())
    finally:
        await db.close()
    assert first.sent_24h == 1 and second.sent_24h == 0
    assert sent == [(str(ana), "reminder_24h")]


async def test_completion_closes_events_that_ended(clean_db):
    add_event(clean_db, hours_from_now=-3)
    add_event(clean_db, hours_from_now=5)
    db = await open_db(clean_db)
    try:
        await run_completion(db)
    finally:
        await db.close()
    assert sorted(sql(clean_db, "select status::text from events")) == [("completed",), ("open",)]
