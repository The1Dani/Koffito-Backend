import json
import uuid

import httpx

OTHER = uuid.UUID("44444444-4444-4444-8444-444444444444")
EVENT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def test_get_user_returns_the_public_profile(client, backend, auth):
    card = {
        "id": str(OTHER),
        "name": "Gabi",
        "emoji": "🍵",
        "gender": "female",
        "age": 28,
        "languages": ["ro"],
        "occupation": None,
        "favoriteCoffee": "latte",
        "survey": {},
        "stats": {"coffeeTalks": 1, "cafesVisited": 1, "peopleMet": 3},
    }
    backend.on("POST", "/rpc/get_public_profile", httpx.Response(200, json=card))
    r = client.get(f"/users/{OTHER}", headers=auth)
    assert r.status_code == 200
    assert r.json() == card
    call = backend.calls("POST", "/rpc/get_public_profile")[0]
    assert json.loads(call.content) == {"p_user_id": str(OTHER)}


def test_get_user_hidden_or_missing_is_404(client, backend, auth):
    backend.on("POST", "/rpc/get_public_profile", httpx.Response(200, json=None))
    r = client.get(f"/users/{OTHER}", headers=auth)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "profile_not_found"


def test_get_user_requires_auth(client):
    assert client.get(f"/users/{OTHER}").status_code == 401


def test_create_report_sets_reporter_from_token(client, backend, auth, user_id):
    row = {
        "id": "55555555-5555-4555-8555-555555555555",
        "reason": "rude",
        "details": "was rude to everyone at the table",
        "status": "open",
        "event_id": str(EVENT_ID),
        "reported_user_id": str(OTHER),
        "created_at": "2026-09-24T10:00:00+00:00",
    }
    backend.on("POST", "/reports", httpx.Response(201, json=[row]))
    r = client.post(
        "/reports",
        headers=auth,
        json={
            "reported_user_id": str(OTHER),
            "event_id": str(EVENT_ID),
            "reason": "rude",
            "details": "was rude to everyone at the table",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "open"
    call = backend.calls("POST", "/reports")[0]
    body = json.loads(call.content)
    assert body["reporter_id"] == str(user_id)
    assert body["reported_user_id"] == str(OTHER)
    assert body["reason"] == "rude"
    assert call.headers["prefer"] == "return=representation"
    assert "id" in call.url.params["select"]


def test_create_report_validation(client, backend, auth):
    base = {"reason": "other", "details": "long enough details here"}
    assert (
        client.post("/reports", headers=auth, json={**base, "reporter_id": "x"}).status_code == 422
    )
    assert (
        client.post("/reports", headers=auth, json={**base, "details": "short"}).status_code == 422
    )
    assert client.post("/reports", headers=auth, json={**base, "reason": "meh"}).status_code == 422
    assert backend.calls("POST", "/reports") == []


def test_create_report_with_unknown_event_is_422(client, backend, auth):
    backend.on(
        "POST",
        "/reports",
        httpx.Response(
            409, json={"code": "23503", "message": "fk violation", "details": "Key (event_id)..."}
        ),
    )
    r = client.post(
        "/reports", headers=auth, json={"reason": "other", "details": "long enough details here"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_reference"
