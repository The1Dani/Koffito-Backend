import json
from datetime import UTC, date, datetime, timedelta

import httpx

ME = {
    "id": "11111111-1111-4111-8111-111111111111",
    "name": "Sergiu",
    "emoji": "☕",
    "gender": "male",
    "age": 30,
    "languages": ["en", "ro"],
    "occupation": "dev",
    "favoriteCoffee": "flat white",
    "survey": {"q1": ["a"]},
    "stats": {"coffeeTalks": 2, "cafesVisited": 1, "peopleMet": 5},
    "isAdmin": False,
    "onboarded": True,
    "settings": {"notificationsEnabled": True, "remindersEnabled": False},
}

PROFILE_ROW = {
    "id": "11111111-1111-4111-8111-111111111111",
    "display_name": "Sergiu",
    "avatar_emoji": "☕",
    "avatar_url": None,
    "gender": "male",
    "date_of_birth": "1995-01-01",
    "occupation": "dev",
    "favorite_coffee": "flat white",
    "onboarded_at": "2026-09-22T12:50:25+00:00",
    "created_at": "2026-09-22T12:44:10+00:00",
    "updated_at": "2026-09-24T10:00:00+00:00",
}


def test_all_me_routes_require_auth(client):
    for method, path in [
        ("GET", "/me"),
        ("PATCH", "/me"),
        ("PUT", "/me/languages"),
        ("PATCH", "/me/settings"),
        ("GET", "/me/survey"),
        ("PUT", "/me/survey"),
        ("GET", "/me/events"),
        ("GET", "/me/venues"),
    ]:
        r = client.request(method, path)
        assert r.status_code == 401, (method, path)
        assert r.json()["error"]["code"] == "missing_token"


def test_get_me_calls_get_me_with_the_users_token(client, backend, auth, token):
    backend.on("POST", "/rpc/get_me", httpx.Response(200, json=ME))
    r = client.get("/me", headers=auth)
    assert r.status_code == 200
    assert r.json() == ME
    call = backend.calls("POST", "/rpc/get_me")[0]
    assert call.headers["authorization"] == f"Bearer {token}"
    assert call.headers["apikey"] == "pub-key"
    assert call.headers["x-koffito-backend-key"] == "backend-key"
    assert json.loads(call.content) == {}


def test_get_me_without_profile_is_404(client, backend, auth):
    backend.on("POST", "/rpc/get_me", httpx.Response(200, json=None))
    r = client.get("/me", headers=auth)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "profile_not_found"


def test_patch_me_updates_only_the_users_row(client, backend, auth, user_id):
    backend.on("PATCH", "/profiles", httpx.Response(200, json=[PROFILE_ROW]))
    r = client.patch(
        "/me",
        headers=auth,
        json={"display_name": "Sergiu", "avatar_emoji": "☕", "onboarded": True},
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Sergiu"
    assert r.json()["onboarded_at"] == "2026-09-22T12:50:25Z"
    call = backend.calls("PATCH", "/profiles")[0]
    assert call.url.params.get_list("id") == [f"eq.{user_id}"]
    assert "display_name" in call.url.params["select"]
    body = json.loads(call.content)
    assert body["display_name"] == "Sergiu"
    assert body["avatar_emoji"] == "☕"
    assert datetime.fromisoformat(body["onboarded_at"]) > datetime.now(UTC) - timedelta(minutes=1)
    assert call.headers["prefer"] == "return=representation"


def test_patch_me_onboarded_false_clears_the_timestamp(client, backend, auth):
    backend.on("PATCH", "/profiles", httpx.Response(200, json=[PROFILE_ROW]))
    client.patch("/me", headers=auth, json={"onboarded": False})
    assert json.loads(backend.calls("PATCH", "/profiles")[0].content) == {"onboarded_at": None}


def test_patch_me_rejects_ids_and_admin_flags(client, backend, auth):
    for body in [{"id": "other"}, {"is_admin": True}, {"display_name": "x", "user_id": "y"}]:
        r = client.patch("/me", headers=auth, json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "validation_error"
    assert backend.calls("PATCH", "/profiles") == []


def test_patch_me_rejects_empty_update_and_minors(client, backend, auth):
    r = client.patch("/me", headers=auth, json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "empty_update"
    too_young = (date.today() - timedelta(days=17 * 365)).isoformat()
    r = client.patch("/me", headers=auth, json={"date_of_birth": too_young})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_patch_me_with_no_matching_row_is_404(client, backend, auth):
    backend.on("PATCH", "/profiles", httpx.Response(200, json=[]))
    r = client.patch("/me", headers=auth, json={"display_name": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "profile_not_found"


def test_put_languages_calls_set_my_languages(client, backend, auth):
    backend.on("POST", "/rpc/set_my_languages", httpx.Response(200, json=["en", "ro"]))
    r = client.put("/me/languages", headers=auth, json={"languages": ["ro", "en"]})
    assert r.status_code == 200
    assert r.json() == {"languages": ["en", "ro"]}
    call = backend.calls("POST", "/rpc/set_my_languages")[0]
    assert json.loads(call.content) == {"p_languages": ["ro", "en"]}


def test_put_languages_validates_values(client, backend, auth):
    assert client.put("/me/languages", headers=auth, json={"languages": ["de"]}).status_code == 422
    assert (
        client.put("/me/languages", headers=auth, json={"languages": ["en", "en"]}).status_code
        == 422
    )
    assert backend.calls("POST", "/rpc/set_my_languages") == []


def test_patch_settings_updates_the_users_settings_row(client, backend, auth, user_id):
    row = {
        "notifications_enabled": True,
        "reminders_enabled": False,
        "updated_at": "2026-09-24T10:00:00+00:00",
    }
    backend.on("PATCH", "/user_settings", httpx.Response(200, json=[row]))
    r = client.patch("/me/settings", headers=auth, json={"reminders_enabled": False})
    assert r.status_code == 200
    assert r.json()["reminders_enabled"] is False
    call = backend.calls("PATCH", "/user_settings")[0]
    assert call.url.params.get_list("user_id") == [f"eq.{user_id}"]
    assert json.loads(call.content) == {"reminders_enabled": False}
    assert client.patch("/me/settings", headers=auth, json={}).status_code == 422


def test_get_survey_reads_the_users_survey(client, backend, auth, user_id):
    row = {"survey_data": {"q1": ["a"]}, "completed_at": None, "updated_at": "2026-09-24T10:00:00Z"}
    backend.on("GET", "/surveys", httpx.Response(200, json=row))
    r = client.get("/me/survey", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"survey_data": {"q1": ["a"]}, "completed_at": None, "completed": False}
    call = backend.calls("GET", "/surveys")[0]
    assert call.url.params.get_list("user_id") == [f"eq.{user_id}"]
    assert call.headers["accept"] == "application/vnd.pgrst.object+json"


def test_get_survey_missing_is_404(client, backend, auth):
    backend.on(
        "GET",
        "/surveys",
        httpx.Response(406, json={"code": "PGRST116", "message": "0 rows", "details": None}),
    )
    r = client.get("/me/survey", headers=auth)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "survey_not_found"


def test_put_survey_upserts_with_user_id_from_token(client, backend, auth, user_id):
    row = {
        "survey_data": {"q1": ["a", "b"]},
        "completed_at": "2026-09-24T10:00:00+00:00",
        "updated_at": "2026-09-24T10:00:00+00:00",
    }
    backend.on("POST", "/surveys", httpx.Response(201, json=[row]))
    r = client.put("/me/survey", headers=auth, json={"survey_data": {"q1": ["a", "b"]}})
    assert r.status_code == 200
    assert r.json()["completed"] is True
    call = backend.calls("POST", "/surveys")[0]
    assert call.url.params.get_list("on_conflict") == ["user_id"]
    assert call.headers["prefer"] == "resolution=merge-duplicates,return=representation"
    body = json.loads(call.content)
    assert body["user_id"] == str(user_id)
    assert body["survey_data"] == {"q1": ["a", "b"]}
    assert body["completed_at"] is not None


def test_put_survey_can_save_a_draft(client, backend, auth):
    backend.on(
        "POST",
        "/surveys",
        httpx.Response(
            201,
            json=[{"survey_data": {}, "completed_at": None, "updated_at": "2026-09-24T10:00:00Z"}],
        ),
    )
    client.put("/me/survey", headers=auth, json={"survey_data": {"q1": ["a"]}, "completed": False})
    assert json.loads(backend.calls("POST", "/surveys")[0].content)["completed_at"] is None


def test_put_survey_validates_shape(client, backend, auth):
    for body in [
        {"survey_data": {"q1": "a"}},
        {"survey_data": []},
        {"user_id": "x", "survey_data": {}},
    ]:
        assert client.put("/me/survey", headers=auth, json=body).status_code == 422, body
    assert backend.calls("POST", "/surveys") == []


def test_get_my_events_and_venues_pass_through_rpc_rows(client, backend, auth):
    event = {
        "id": "22222222-2222-4222-8222-222222222222",
        "event_at": "2026-09-27T06:00:00+00:00",
        "reveal_at": "2026-09-26T06:00:00+00:00",
        "status": "pending",
        "participant_status": "joined",
        "joined": True,
        "blind": True,
        "location_hidden": True,
        "reveal_opened": False,
        "max_participants": 4,
        "cafe": None,
        "participants": None,
        "attended": None,
        "attendance_note": None,
        "my_rating": None,
        "my_comment": None,
    }
    venue = {
        "id": "33333333-3333-4333-8333-333333333333",
        "name": "Tucano",
        "address": "x",
        "mapsUrl": None,
    }
    backend.on("POST", "/rpc/get_my_events", httpx.Response(200, json=[event]))
    backend.on("POST", "/rpc/get_my_visited_venues", httpx.Response(200, json=[venue]))
    events = client.get("/me/events", headers=auth).json()
    assert events[0]["id"] == event["id"]
    assert events[0]["event_at"] == "2026-09-27T06:00:00Z"
    assert events[0]["status"] == "pending"
    assert events[0]["cafe"] is None
    venues = client.get("/me/venues", headers=auth).json()
    assert venues[0]["name"] == "Tucano"
    assert venues[0]["popularTimes"] == []
