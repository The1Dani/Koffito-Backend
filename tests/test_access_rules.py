"""Who may see and do what — the rules that used to be Supabase RLS, now our SQL + API.

Every test goes through the real API and database.
"""

from datetime import UTC, datetime, timedelta

from tests.conftest import signup, sql

SURVEY = {"survey_data": {"why": ["socialize"], "personality": ["extrovert"]}, "completed": True}


def add_venue(dsn, name="Naringi"):
    ((vid,),) = sql(
        dsn, "insert into venues (name, address) values (%s, 'Strada 1') returning id", [name]
    )
    return str(vid)


def add_event(dsn, *, hours_from_now=48, reveal_in_hours=24, venue=None, status="open"):
    event_at = datetime.now(UTC) + timedelta(hours=hours_from_now)
    reveal_at = event_at - timedelta(hours=reveal_in_hours)
    ((eid,),) = sql(
        dsn,
        "insert into events (event_at, reveal_at, default_venue_id, status) values (%s, %s, %s, %s)"
        " returning id",
        [event_at, reveal_at, venue, status],
    )
    return str(eid)


def uid(client, headers):
    return client.get("/me", headers=headers).json()["id"]


def make_admin(dsn, email):
    sql(
        dsn,
        "update profiles set is_admin = true from users where users.id = profiles.id"
        " and users.email = %s",
        [email],
    )


# --- own data only -----------------------------------------------------------------------------


def test_profile_edits_only_touch_the_callers_row(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com", name="Ana")
    signup(client, outbox, "bob@example.com", name="Bob")
    r = client.patch("/me", headers=ana, json={"display_name": "Ana M", "occupation": "Student"})
    assert r.status_code == 200
    assert sorted(sql(clean_db, "select display_name from profiles")) == [("Ana M",), ("Bob",)]


def test_admin_flag_cannot_be_set_through_the_api(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    r = client.patch("/me", headers=ana, json={"is_admin": True})
    assert r.status_code == 422
    assert sql(clean_db, "select is_admin from profiles") == [(False,)]


def test_survey_is_private_to_its_owner(client, outbox):
    ana = signup(client, outbox, "ana@example.com")
    bob = signup(client, outbox, "bob@example.com")
    assert client.put("/me/survey", headers=ana, json=SURVEY).status_code in (200, 201)
    assert client.get("/me/survey", headers=ana).json()["completed"] is True
    assert client.get("/me/survey", headers=bob).status_code == 404


def test_strangers_cannot_read_each_others_profiles(client, outbox):
    ana = signup(client, outbox, "ana@example.com")
    bob = signup(client, outbox, "bob@example.com")
    assert client.get(f"/users/{uid(client, bob)}", headers=ana).status_code == 404
    assert client.get(f"/users/{uid(client, ana)}", headers=ana).status_code == 200


def test_groupmates_see_each_other_only_after_the_reveal(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    bob = signup(client, outbox, "bob@example.com")
    venue = add_venue(clean_db)
    event = add_event(clean_db, venue=venue, hours_from_now=48, reveal_in_hours=24)
    for h in (ana, bob):
        client.put("/me/survey", headers=h, json=SURVEY)
        assert client.post(f"/events/{event}/join", headers=h).status_code == 204
    ((gid,),) = sql(clean_db, "insert into groups (event_id) values (%s) returning id", [event])
    sql(clean_db, "update event_participants set group_id = %s, status = 'matched'", [gid])

    bob_id = uid(client, bob)
    mine = client.get("/me/events", headers=ana).json()[0]
    assert mine["location_hidden"] is True and mine["cafe"] is None and mine["participants"] is None
    assert client.get(f"/users/{bob_id}", headers=ana).status_code == 404

    sql(clean_db, "update events set reveal_at = now() - interval '1 minute'")
    mine = client.get("/me/events", headers=ana).json()[0]
    assert mine["cafe"]["name"] == "Naringi"
    assert [p["name"] for p in mine["participants"]] == ["Ana"]  # bob signed up as Ana too
    assert client.get(f"/users/{bob_id}", headers=ana).status_code == 200


def test_open_events_never_leak_the_hidden_cafe(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    add_event(clean_db, venue=add_venue(clean_db))
    (event,) = client.get("/events", headers=ana).json()
    assert "default_venue_id" not in event and "cafe" not in event


# --- event rules -------------------------------------------------------------------------------


def test_joining_requires_a_completed_survey(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    event = add_event(clean_db)
    r = client.post(f"/events/{event}/join", headers=ana)
    assert r.status_code == 409 and r.json()["error"]["code"] == "survey_incomplete"
    client.put("/me/survey", headers=ana, json=SURVEY)
    assert client.post(f"/events/{event}/join", headers=ana).status_code == 204
    assert client.get("/events", headers=ana).json()[0]["joined"] is True


def test_overlapping_coffee_talks_are_refused(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    client.put("/me/survey", headers=ana, json=SURVEY)
    first, second = add_event(clean_db, hours_from_now=48), add_event(clean_db, hours_from_now=49)
    assert client.post(f"/events/{first}/join", headers=ana).status_code == 204
    r = client.post(f"/events/{second}/join", headers=ana)
    assert r.status_code == 409 and r.json()["error"]["code"] == "time_conflict"


def test_leave_then_rejoin(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    client.put("/me/survey", headers=ana, json=SURVEY)
    event = add_event(clean_db)
    client.post(f"/events/{event}/join", headers=ana)
    assert client.post(f"/events/{event}/leave", headers=ana).status_code == 204
    assert client.post(f"/events/{event}/leave", headers=ana).status_code == 409
    assert client.post(f"/events/{event}/join", headers=ana).status_code == 204


def test_rating_requires_having_attended(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    client.put("/me/survey", headers=ana, json=SURVEY)
    event = add_event(clean_db)
    client.post(f"/events/{event}/join", headers=ana)
    r = client.put(f"/events/{event}/rating", headers=ana, json={"rating": 5, "comment": "Lovely"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_attended"
    sql(
        clean_db,
        "update events set event_at = now() - interval '1 hour',"
        " reveal_at = now() - interval '2 hours'",
    )
    assert (
        client.post(f"/events/{event}/attendance", headers=ana, json={"happened": True}).status_code
        == 204
    )
    r = client.put(f"/events/{event}/rating", headers=ana, json={"rating": 5, "comment": "Lovely"})
    assert r.status_code == 200 and r.json()["rating"] == 5


def test_report_is_filed_as_the_caller_whatever_the_body_says(client, outbox, clean_db):
    ana = signup(client, outbox, "ana@example.com")
    bob = signup(client, outbox, "bob@example.com")
    r = client.post(
        "/reports",
        headers=ana,
        json={
            "reason": "rude",
            "details": "Was rude during the coffee talk.",
            "reporter_id": uid(client, bob),
        },
    )
    assert r.status_code in (201, 422)  # unknown fields are refused outright…
    if r.status_code == 201:  # …or ignored; either way the reporter is Ana
        assert sql(clean_db, "select reporter_id::text from reports") == [(uid(client, ana),)]


# --- admin -------------------------------------------------------------------------------------


def test_admin_routes_are_closed_to_regular_users(client, outbox):
    ana = signup(client, outbox, "ana@example.com")
    for method, path in [
        ("get", "/admin/events"),
        ("get", "/admin/venues"),
        ("get", "/admin/reports"),
        ("post", "/admin/venues"),
    ]:
        r = getattr(client, method)(path, headers=ana, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 403, (path, r.text)
        assert r.json()["error"]["code"] == "admin_required"


def test_admin_can_manage_venues_events_and_reports(client, outbox, clean_db):
    admin = signup(client, outbox, "admin@example.com", name="Admin")
    make_admin(clean_db, "admin@example.com")
    assert client.get("/me", headers=admin).json()["isAdmin"] is True

    r = client.post("/admin/venues", headers=admin, json={"name": "Pasio", "address": "Strada 2"})
    assert r.status_code == 201
    venue = r.json()["id"]
    when = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    r = client.post(
        "/admin/events", headers=admin, json={"event_at": when, "default_venue_id": venue}
    )
    assert r.status_code == 201
    event = r.json()["id"]
    assert client.get(f"/admin/events/{event}", headers=admin).json()["default_venue_id"] == venue

    ana = signup(client, outbox, "ana@example.com")
    client.post("/reports", headers=ana, json={"reason": "other", "details": "Something happened."})
    (report,) = client.get("/admin/reports", headers=admin).json()["items"]
    r = client.patch(f"/admin/reports/{report['id']}", headers=admin, json={"status": "reviewing"})
    assert r.status_code == 200 and r.json()["handled_by"] == uid(client, admin)
