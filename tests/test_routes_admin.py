import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

EVENT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
VENUE_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
REPORT_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")

EVENT_ROW = {
    "id": str(EVENT_ID),
    "title": None,
    "event_at": "2026-09-27T06:00:00+00:00",
    "capacity": 40,
    "target_group_size": 4,
    "reveal_at": "2026-09-26T06:00:00+00:00",
    "default_venue_id": str(VENUE_ID),
    "status": "open",
    "created_by": "11111111-1111-4111-8111-111111111111",
    "created_at": "2026-09-24T09:53:20+00:00",
    "updated_at": "2026-09-24T09:53:20+00:00",
}
VENUE_ROW = {
    "id": str(VENUE_ID),
    "name": "Tucano Coffee",
    "description": "",
    "photo_url": None,
    "address": "Str. Ismail 33",
    "website": None,
    "phone": None,
    "maps_url": None,
    "google_place_id": None,
    "latitude": 47.02,
    "longitude": 28.83,
    "rating": 4.5,
    "popular_times": [10, 20, 30, 40, 50, 60, 70],
    "capacity": 24,
    "is_active": True,
    "created_at": "2026-09-24T09:00:00+00:00",
}
REPORT_ROW = {
    "id": str(REPORT_ID),
    "reason": "rude",
    "details": "was rude to everyone",
    "status": "open",
    "created_at": "2026-09-24T10:00:00+00:00",
    "updated_at": "2026-09-24T10:00:00+00:00",
    "event_id": str(EVENT_ID),
    "reporter_id": "11111111-1111-4111-8111-111111111111",
    "reported_by": "Sergiu",
    "reported_user_id": "44444444-4444-4444-8444-444444444444",
    "reported_user_name": "Gabi",
    "handled_by": None,
}


@pytest.fixture
def admin(backend):
    backend.always("POST", "/rpc/is_admin", httpx.Response(200, json=True))
    return backend


def test_admin_routes_reject_non_admins(client, backend, auth):
    backend.always("POST", "/rpc/is_admin", httpx.Response(200, json=False))
    for method, path in [
        ("GET", "/admin/events"),
        ("POST", "/admin/events"),
        ("GET", "/admin/venues"),
        ("GET", "/admin/reports"),
        ("PATCH", f"/admin/reports/{REPORT_ID}"),
    ]:
        r = client.request(method, path, headers=auth, json={})
        assert r.status_code == 403, (method, path, r.text)
        assert r.json()["error"]["code"] == "admin_required"
    assert client.get("/admin/events").status_code == 401


def test_list_events_uses_admin_rpc_with_filters_and_count(client, admin, auth):
    admin.on(
        "POST",
        "/rpc/admin_list_events",
        httpx.Response(200, json=[EVENT_ROW], headers={"Content-Range": "0-0/7"}),
    )
    r = client.get(
        "/admin/events",
        headers=auth,
        params={"status": "open", "from": "2026-09-01T00:00:00Z", "limit": 10, "offset": 20},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 7 and body["limit"] == 10 and body["offset"] == 20
    assert body["items"][0]["default_venue_id"] == str(VENUE_ID)
    call = admin.calls("POST", "/rpc/admin_list_events")[0]
    assert call.url.params.get_list("status") == ["eq.open"]
    assert call.url.params.get_list("event_at") == ["gte.2026-09-01T00:00:00+00:00"]
    assert call.url.params.get_list("order") == ["event_at.desc"]
    assert call.url.params.get_list("limit") == ["10"]
    assert call.url.params.get_list("offset") == ["20"]
    assert call.headers["prefer"] == "count=exact"


def test_get_event_single_and_404(client, admin, auth):
    admin.on("POST", "/rpc/admin_list_events", httpx.Response(200, json=EVENT_ROW))
    r = client.get(f"/admin/events/{EVENT_ID}", headers=auth)
    assert r.status_code == 200
    assert r.json()["id"] == str(EVENT_ID)
    call = admin.calls("POST", "/rpc/admin_list_events")[0]
    assert call.url.params.get_list("id") == [f"eq.{EVENT_ID}"]
    assert call.headers["accept"] == "application/vnd.pgrst.object+json"
    admin.on(
        "POST",
        "/rpc/admin_list_events",
        httpx.Response(406, json={"code": "PGRST116", "message": "0 rows", "details": None}),
    )
    r = client.get(f"/admin/events/{EVENT_ID}", headers=auth)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "event_not_found"


def test_create_event_calls_create_event_then_reads_it_back(client, admin, auth):
    admin.on("POST", "/rpc/create_event", httpx.Response(200, json=str(EVENT_ID)))
    admin.on("POST", "/rpc/admin_list_events", httpx.Response(200, json=EVENT_ROW))
    event_at = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    r = client.post(
        "/admin/events",
        headers=auth,
        json={"event_at": event_at, "default_venue_id": str(VENUE_ID), "title": "Saturday"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == str(EVENT_ID)
    params = json.loads(admin.calls("POST", "/rpc/create_event")[0].content)
    assert params == {
        "p_event_at": event_at,
        "p_target_group_size": 4,
        "p_default_venue_id": str(VENUE_ID),
        "p_location_hidden": True,
        "p_capacity": 40,
        "p_title": "Saturday",
        "p_status": "open",
    }


def test_create_event_validation(client, admin, auth):
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert client.post("/admin/events", headers=auth, json={"event_at": past}).status_code == 422
    assert (
        client.post(
            "/admin/events", headers=auth, json={"event_at": future, "target_group_size": 9}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/admin/events", headers=auth, json={"event_at": future, "status": "completed"}
        ).status_code
        == 422
    )
    assert admin.calls("POST", "/rpc/create_event") == []


def test_patch_event_updates_then_reads_back(client, admin, auth):
    admin.on("PATCH", "/events", httpx.Response(200, json=[{"id": str(EVENT_ID)}]))
    cancelled = {**EVENT_ROW, "status": "cancelled"}
    admin.on("POST", "/rpc/admin_list_events", httpx.Response(200, json=cancelled))
    r = client.patch(f"/admin/events/{EVENT_ID}", headers=auth, json={"status": "cancelled"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    call = admin.calls("PATCH", "/events")[0]
    assert call.url.params.get_list("id") == [f"eq.{EVENT_ID}"]
    assert call.url.params.get_list("select") == ["id"]
    assert json.loads(call.content) == {"status": "cancelled"}


def test_patch_event_404_and_empty(client, admin, auth):
    admin.on("PATCH", "/events", httpx.Response(200, json=[]))
    r = client.patch(f"/admin/events/{EVENT_ID}", headers=auth, json={"title": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "event_not_found"
    r = client.patch(f"/admin/events/{EVENT_ID}", headers=auth, json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "empty_update"


def test_event_participants_embed_profile(client, admin, auth):
    row = {
        "id": "66666666-6666-4666-8666-666666666666",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "status": "joined",
        "group_id": None,
        "joined_at": "2026-09-24T10:00:00+00:00",
        "confirmed_24h_at": None,
        "confirmed_3h_at": None,
        "cancelled_at": None,
        "attended": None,
        "attendance_note": None,
        "reveal_opened_at": None,
        "reminded_24h_at": None,
        "reminded_3h_at": None,
        "profile": {"display_name": "Sergiu", "avatar_emoji": "☕"},
    }
    admin.on("GET", "/event_participants", httpx.Response(200, json=[row]))
    r = client.get(f"/admin/events/{EVENT_ID}/participants", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()[0]["profile"] == {"display_name": "Sergiu", "avatar_emoji": "☕"}
    call = admin.calls("GET", "/event_participants")[0]
    assert call.url.params.get_list("event_id") == [f"eq.{EVENT_ID}"]
    assert "profile:profiles(display_name,avatar_emoji)" in call.url.params["select"]
    assert call.url.params.get_list("order") == ["joined_at.asc"]


def test_venues_list_create_get_patch_soft_delete(client, admin, auth):
    admin.on("GET", "/venues", httpx.Response(200, json=[VENUE_ROW]))
    r = client.get("/admin/venues", headers=auth)
    assert r.status_code == 200 and r.json()[0]["name"] == "Tucano Coffee"
    call = admin.calls("GET", "/venues")[0]
    assert call.url.params.get_list("is_active") == ["eq.true"]
    assert call.url.params.get_list("order") == ["name.asc"]

    admin.on("GET", "/venues", httpx.Response(200, json=[VENUE_ROW]))
    client.get("/admin/venues", headers=auth, params={"include_inactive": "true"})
    assert admin.calls("GET", "/venues")[1].url.params.get_list("is_active") == []

    admin.on("POST", "/venues", httpx.Response(201, json=[VENUE_ROW]))
    r = client.post(
        "/admin/venues",
        headers=auth,
        json={"name": "Tucano Coffee", "address": "Str. Ismail 33", "capacity": 24, "rating": 4.5},
    )
    assert r.status_code == 201, r.text
    body = json.loads(admin.calls("POST", "/venues")[0].content)
    assert body == {
        "name": "Tucano Coffee",
        "address": "Str. Ismail 33",
        "capacity": 24,
        "rating": 4.5,
    }

    admin.on("GET", "/venues", httpx.Response(200, json=VENUE_ROW))
    r = client.get(f"/admin/venues/{VENUE_ID}", headers=auth)
    assert r.status_code == 200 and r.json()["id"] == str(VENUE_ID)
    assert admin.calls("GET", "/venues")[2].headers["accept"] == "application/vnd.pgrst.object+json"

    admin.on("PATCH", "/venues", httpx.Response(200, json=[{**VENUE_ROW, "capacity": 30}]))
    r = client.patch(f"/admin/venues/{VENUE_ID}", headers=auth, json={"capacity": 30})
    assert r.status_code == 200 and r.json()["capacity"] == 30
    assert admin.calls("PATCH", "/venues")[0].url.params.get_list("id") == [f"eq.{VENUE_ID}"]

    admin.on("PATCH", "/venues", httpx.Response(200, json=[{**VENUE_ROW, "is_active": False}]))
    r = client.delete(f"/admin/venues/{VENUE_ID}", headers=auth)
    assert r.status_code == 204
    assert json.loads(admin.calls("PATCH", "/venues")[1].content) == {"is_active": False}


def test_venue_validation(client, admin, auth):
    bad = [
        {"name": "", "address": "x"},
        {"name": "x", "address": "x", "capacity": 0},
        {"name": "x", "address": "x", "rating": 6},
        {"name": "x", "address": "x", "popular_times": [1, 2, 3]},
        {"name": "x", "address": "x", "id": str(VENUE_ID)},
    ]
    for body in bad:
        assert client.post("/admin/venues", headers=auth, json=body).status_code == 422, body
    admin.on("PATCH", "/venues", httpx.Response(200, json=[]))
    r = client.patch(f"/admin/venues/{VENUE_ID}", headers=auth, json={"name": "y"})
    assert r.status_code == 404


def test_reports_list_and_triage(client, admin, auth, user_id):
    admin.on(
        "GET",
        "/admin_reports",
        httpx.Response(200, json=[REPORT_ROW], headers={"Content-Range": "0-0/1"}),
    )
    r = client.get("/admin/reports", headers=auth, params={"status": "open"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["reported_by"] == "Sergiu"
    call = admin.calls("GET", "/admin_reports")[0]
    assert call.url.params.get_list("status") == ["eq.open"]
    assert call.url.params.get_list("order") == ["created_at.desc"]
    assert call.headers["prefer"] == "count=exact"

    admin.on(
        "PATCH",
        "/reports",
        httpx.Response(
            200,
            json=[
                {
                    "id": str(REPORT_ID),
                    "status": "reviewing",
                    "handled_by": str(user_id),
                    "updated_at": "2026-09-24T11:00:00+00:00",
                }
            ],
        ),
    )
    r = client.patch(f"/admin/reports/{REPORT_ID}", headers=auth, json={"status": "reviewing"})
    assert r.status_code == 200, r.text
    assert r.json()["handled_by"] == str(user_id)
    call = admin.calls("PATCH", "/reports")[0]
    assert call.url.params.get_list("id") == [f"eq.{REPORT_ID}"]
    assert json.loads(call.content) == {"status": "reviewing", "handled_by": str(user_id)}

    admin.on("PATCH", "/reports", httpx.Response(200, json=[]))
    r = client.patch(f"/admin/reports/{REPORT_ID}", headers=auth, json={"status": "resolved"})
    assert r.status_code == 404
    r = client.patch(f"/admin/reports/{REPORT_ID}", headers=auth, json={"status": "closed"})
    assert r.status_code == 422


def test_admin_rate_limit_runs_before_the_admin_check(signing_key, backend, auth):
    """A non-admin must not be able to drive unbounded is_admin() calls through /admin/*."""
    import httpx as _httpx

    from koffito.core.config import Settings
    from koffito.main import create_app
    from tests.support import SUPABASE_URL

    settings = Settings(
        supabase_url=SUPABASE_URL,
        supabase_publishable_key="pub-key",
        koffito_backend_key="bk",
        rate_limit_admin_limit=2,
        rate_limit_admin_window_seconds=60,
        _env_file=None,
    )
    backend.always("POST", "/rpc/is_admin", _httpx.Response(200, json=False))
    app = create_app(settings, transport=_httpx.MockTransport(backend))
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.get("/admin/events", headers=auth).status_code == 403
        assert client.get("/admin/events", headers=auth).status_code == 403
        assert len(backend.calls("POST", "/rpc/is_admin")) == 2
        r = client.get("/admin/events", headers=auth)
    assert r.status_code == 429
    assert len(backend.calls("POST", "/rpc/is_admin")) == 2  # limited before touching the DB
