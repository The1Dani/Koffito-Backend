import json
import uuid

import httpx
import pytest

EVENT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def rpc_error(name: str) -> httpx.Response:
    return httpx.Response(
        400, json={"code": "P0001", "message": name, "details": None, "hint": None}
    )


def test_events_routes_require_auth(client):
    assert client.get("/events").status_code == 401
    assert client.post(f"/events/{EVENT_ID}/join").status_code == 401
    assert client.put(f"/events/{EVENT_ID}/rating", json={"rating": 5}).status_code == 401


def test_list_open_events(client, backend, auth, token):
    row = {
        "id": str(EVENT_ID),
        "event_at": "2026-09-27T06:00:00+00:00",
        "max_participants": 4,
        "spots_left": 39,
        "joined": False,
    }
    backend.on("POST", "/rpc/get_open_events", httpx.Response(200, json=[row]))
    r = client.get("/events", headers=auth)
    assert r.status_code == 200
    assert r.json() == [{**row, "event_at": "2026-09-27T06:00:00Z"}]
    assert (
        backend.calls("POST", "/rpc/get_open_events")[0].headers["authorization"]
        == f"Bearer {token}"
    )


@pytest.mark.parametrize(
    ("path", "rpc", "body", "expected_params"),
    [
        ("join", "join_event", None, {"p_event_id": str(EVENT_ID)}),
        ("leave", "leave_event", None, {"p_event_id": str(EVENT_ID)}),
        (
            "confirm",
            "confirm_event",
            {"stage": "24h"},
            {"p_event_id": str(EVENT_ID), "p_stage": "24h"},
        ),
        ("reveal", "open_reveal", None, {"p_event_id": str(EVENT_ID)}),
        (
            "attendance",
            "report_attendance",
            {"happened": False, "note": "nobody came"},
            {"p_event_id": str(EVENT_ID), "p_happened": False, "p_note": "nobody came"},
        ),
    ],
)
def test_event_actions_call_the_rpc_and_return_204(
    client, backend, auth, path, rpc, body, expected_params
):
    backend.on("POST", f"/rpc/{rpc}", httpx.Response(204))
    r = client.post(f"/events/{EVENT_ID}/{path}", headers=auth, json=body)
    assert r.status_code == 204, r.text
    assert r.content == b""
    call = backend.calls("POST", f"/rpc/{rpc}")[0]
    assert json.loads(call.content) == expected_params


def test_attendance_note_is_optional(client, backend, auth):
    backend.on("POST", "/rpc/report_attendance", httpx.Response(204))
    client.post(f"/events/{EVENT_ID}/attendance", headers=auth, json={"happened": True})
    body = json.loads(backend.calls("POST", "/rpc/report_attendance")[0].content)
    assert body == {"p_event_id": str(EVENT_ID), "p_happened": True, "p_note": None}


@pytest.mark.parametrize(
    ("path", "rpc", "body", "name", "status"),
    [
        ("join", "join_event", None, "survey_incomplete", 409),
        ("join", "join_event", None, "event_full", 409),
        ("join", "join_event", None, "time_conflict", 409),
        ("join", "join_event", None, "event_not_open", 409),
        ("leave", "leave_event", None, "nothing_to_cancel", 409),
        ("confirm", "confirm_event", {"stage": "3h"}, "event_not_confirmable", 409),
        ("confirm", "confirm_event", {"stage": "3h"}, "nothing_to_confirm", 409),
        ("reveal", "open_reveal", None, "not_revealed_yet", 409),
    ],
)
def test_rpc_business_errors_are_mapped(client, backend, auth, path, rpc, body, name, status):
    backend.on("POST", f"/rpc/{rpc}", rpc_error(name))
    r = client.post(f"/events/{EVENT_ID}/{path}", headers=auth, json=body)
    assert r.status_code == status
    assert r.json()["error"]["code"] == name


def test_confirm_validates_stage(client, backend, auth):
    r = client.post(f"/events/{EVENT_ID}/confirm", headers=auth, json={"stage": "1h"})
    assert r.status_code == 422
    assert backend.calls("POST", "/rpc/confirm_event") == []


def test_event_id_must_be_a_uuid(client, auth):
    assert client.post("/events/not-a-uuid/join", headers=auth).status_code == 422


def test_rate_event_calls_the_rpc(client, backend, auth):
    row = {
        "event_id": str(EVENT_ID),
        "rating": 5,
        "comment": "great",
        "created_at": "2026-09-24T10:00:00+00:00",
        "updated_at": "2026-09-24T10:00:00+00:00",
    }
    backend.on("POST", "/rpc/rate_event", httpx.Response(200, json=row))
    r = client.put(
        f"/events/{EVENT_ID}/rating", headers=auth, json={"rating": 5, "comment": "great"}
    )
    assert r.status_code == 200
    assert r.json()["rating"] == 5
    call = backend.calls("POST", "/rpc/rate_event")[0]
    assert json.loads(call.content) == {
        "p_event_id": str(EVENT_ID),
        "p_rating": 5,
        "p_comment": "great",
    }


def test_rate_event_validates_and_maps_not_attended(client, backend, auth):
    assert (
        client.put(f"/events/{EVENT_ID}/rating", headers=auth, json={"rating": 6}).status_code
        == 422
    )
    assert (
        client.put(f"/events/{EVENT_ID}/rating", headers=auth, json={"rating": 0}).status_code
        == 422
    )
    assert (
        client.put(
            f"/events/{EVENT_ID}/rating", headers=auth, json={"rating": 3, "user_id": "x"}
        ).status_code
        == 422
    )
    backend.on("POST", "/rpc/rate_event", rpc_error("not_attended"))
    r = client.put(f"/events/{EVENT_ID}/rating", headers=auth, json={"rating": 3})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_attended"
