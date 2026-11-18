"""Regression tests for issues found in review."""

from tests.conftest import signup


def test_pre_registration_cannot_hijack_the_account(client, outbox):
    attacker, victim = "Attacker-pass-91", "Victim-pass-27x"
    assert (
        client.post(
            "/auth/register",
            json={"email": "v@example.com", "password": attacker, "first_name": "Evil"},
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/auth/register",
            json={"email": "v@example.com", "password": victim, "first_name": "Vera"},
        ).status_code
        == 202
    )
    token = outbox.token("v@example.com", "verify-email")  # the victim's (latest) link
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    ok = lambda p: client.post("/auth/login", json={"email": "v@example.com", "password": p})  # noqa: E731
    assert ok(victim).status_code == 200
    assert ok(attacker).status_code == 401


def test_languages_are_saved_as_a_postgres_array(client, outbox):
    headers = signup(client, outbox, "ana@example.com")
    r = client.put("/me/languages", headers=headers, json={"languages": ["ro", "en"]})
    assert r.status_code == 200, r.text
    assert sorted(client.get("/me", headers=headers).json()["languages"]) == ["en", "ro"]


def test_admin_venue_with_popular_times(client, outbox, clean_db):
    from tests.conftest import sql

    headers = signup(client, outbox, "admin@example.com")
    sql(clean_db, "update profiles set is_admin = true")
    r = client.post(
        "/admin/venues",
        headers=headers,
        json={"name": "Pasio", "address": "Strada 2", "popular_times": [1, 2, 3, 4, 5, 6, 7]},
    )
    assert r.status_code == 201, r.text
    r = client.patch(
        f"/admin/venues/{r.json()['id']}",
        headers=headers,
        json={"popular_times": [7, 6, 5, 4, 3, 2, 1]},
    )
    assert r.status_code == 200, r.text


def test_open_events_show_the_cafe_only_when_not_blind(client, outbox, clean_db):
    from datetime import UTC, datetime, timedelta

    from tests.conftest import sql

    headers = signup(client, outbox, "ana@example.com")
    ((venue,),) = sql(
        clean_db, "insert into venues (name, address) values ('Naringi', 'x') returning id"
    )
    when = datetime.now(UTC) + timedelta(days=3)
    # blind: reveal a day before; open: revealed at creation
    sql(
        clean_db,
        "insert into events (event_at, default_venue_id, status) values (%s, %s, 'open')",
        [when, venue],
    )
    sql(
        clean_db,
        "insert into events (event_at, reveal_at, default_venue_id, status, created_at)"
        " values (%s, now() - interval '1 minute', %s, 'open', now())",
        [when + timedelta(hours=5), venue],
    )
    blind, open_ = client.get("/events", headers=headers).json()
    assert blind["blind"] is True and blind["cafe"] is None
    assert open_["blind"] is False and open_["cafe"]["name"] == "Naringi"


def test_page_past_the_end_still_reports_the_total(client, outbox, clean_db):
    from tests.conftest import sql

    admin = signup(client, outbox, "admin@example.com")
    sql(clean_db, "update profiles set is_admin = true")
    for i in range(3):
        client.post(
            "/reports", headers=admin, json={"reason": "other", "details": f"Report number {i}."}
        )
    page = client.get("/admin/reports?limit=2&offset=10", headers=admin).json()
    assert page["items"] == [] and page["total"] == 3


async def test_reminder_email_names_the_local_time_and_links_the_event(clean_db):
    from datetime import UTC, datetime

    from koffito.db import Database
    from koffito.jobs.notifier import EmailNotifier
    from tests.conftest import make_settings, sql

    ((uid,),) = sql(
        clean_db,
        "insert into users (email, password_hash, email_verified_at)"
        " values ('ana@example.com', 'x', now()) returning id",
    )
    sent = []

    class Mailer:
        async def send(self, mail):
            sent.append(mail)

        def reminder(self, to, kind, at, event_id):
            return (to, kind, at.strftime("%H:%M"), event_id)

    db = Database(clean_db, max_size=1)
    await db.open()
    try:
        notifier = EmailNotifier(db, Mailer(), make_settings())
        at = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)  # 18:00 in Chișinău
        await notifier.send(uid, "reminder_24h", {"event_id": "e1", "event_at": at.isoformat()})
    finally:
        await db.close()
    assert sent == [("ana@example.com", "reminder_24h", "18:00", "e1")]
