import json

import httpx
import pytest

from koffito.supabase.client import Page, ServiceAuth, SupabaseRest, UserAuth
from koffito.supabase.errors import SupabaseError, SupabaseUnavailable

REST = "https://test.supabase.co/rest/v1"
LEGACY_SVC = "eyJhbGciOiJIUzI1NiJ9.legacy.service"


class Recorder:
    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.responses = responses or []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json=[])

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def make(handler, service_key: str | None = LEGACY_SVC) -> SupabaseRest:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseRest(
        http, rest_url=REST, publishable_key="pub-key", service_key=service_key, backend_key="bk"
    )


async def test_user_auth_headers():
    rec = Recorder([httpx.Response(200, json={"id": "u1"})])
    sb = make(rec)
    result = await sb.rpc("get_me", {}, auth=UserAuth("user-jwt"))
    assert result == {"id": "u1"}
    req = rec.last
    assert req.method == "POST"
    assert str(req.url) == f"{REST}/rpc/get_me"
    assert json.loads(req.content) == {}
    assert req.headers["apikey"] == "pub-key"
    assert req.headers["authorization"] == "Bearer user-jwt"
    assert req.headers["x-koffito-backend-key"] == "bk"
    assert req.headers["accept"] == "application/json"


async def test_service_auth_with_legacy_jwt_sends_bearer():
    rec = Recorder()
    await make(rec).select("profiles", auth=ServiceAuth())
    assert rec.last.headers["apikey"] == LEGACY_SVC
    assert rec.last.headers["authorization"] == f"Bearer {LEGACY_SVC}"


async def test_service_auth_with_secret_key_sends_apikey_only():
    rec = Recorder()
    await make(rec, service_key="sb_secret_abc").select("profiles", auth=ServiceAuth())
    assert rec.last.headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in rec.last.headers


async def test_service_auth_without_key_configured_fails_loudly():
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY"):
        await make(Recorder(), service_key=None).select("profiles", auth=ServiceAuth())


async def test_select_encodes_columns_filters_order_and_single():
    rec = Recorder([httpx.Response(200, json={"id": "abc", "is_admin": True})])
    row = await make(rec).select(
        "profiles",
        auth=UserAuth("t"),
        columns="id,is_admin",
        filters=[("id", "eq.abc"), ("status", "in.(joined,matched)")],
        order="created_at.desc",
        limit=5,
        offset=10,
        single=True,
    )
    assert row == {"id": "abc", "is_admin": True}
    req = rec.last
    assert req.method == "GET"
    assert req.url.path == "/rest/v1/profiles"
    assert req.url.params.get_list("select") == ["id,is_admin"]
    assert req.url.params.get_list("id") == ["eq.abc"]
    assert req.url.params.get_list("status") == ["in.(joined,matched)"]
    assert req.url.params.get_list("order") == ["created_at.desc"]
    assert req.url.params.get_list("limit") == ["5"]
    assert req.url.params.get_list("offset") == ["10"]
    assert req.headers["accept"] == "application/vnd.pgrst.object+json"


async def test_repeated_filter_keys_are_preserved():
    rec = Recorder()
    await make(rec).select(
        "event_participants",
        auth=ServiceAuth(),
        filters=[("events.event_at", "gte.2026-01-01"), ("events.event_at", "lte.2026-01-02")],
    )
    assert rec.last.url.params.get_list("events.event_at") == ["gte.2026-01-01", "lte.2026-01-02"]


async def test_select_with_count_returns_page_from_content_range():
    rec = Recorder([httpx.Response(200, json=[{"id": 1}], headers={"Content-Range": "0-0/57"})])
    page = await make(rec).select("events", auth=UserAuth("t"), count=True)
    assert page == Page(items=[{"id": 1}], total=57)
    assert rec.last.headers["prefer"] == "count=exact"


async def test_count_with_empty_result():
    rec = Recorder([httpx.Response(200, json=[], headers={"Content-Range": "*/0"})])
    page = await make(rec).select("events", auth=UserAuth("t"), count=True)
    assert page == Page(items=[], total=0)


async def test_rpc_passes_filters_count_and_single():
    rec = Recorder([httpx.Response(200, json={"id": "e1"})])
    row = await make(rec).rpc(
        "admin_list_events", {}, auth=UserAuth("t"), filters=[("id", "eq.e1")], single=True
    )
    assert row == {"id": "e1"}
    assert rec.last.url.params.get_list("id") == ["eq.e1"]
    assert rec.last.headers["accept"] == "application/vnd.pgrst.object+json"


async def test_insert_returns_representation_by_default():
    rec = Recorder([httpx.Response(201, json=[{"id": "r1", "status": "open"}])])
    rows = await make(rec).insert(
        "reports", {"reason": "rude", "reporter_id": "u1"}, auth=UserAuth("t"), columns="id,status"
    )
    assert rows == [{"id": "r1", "status": "open"}]
    req = rec.last
    assert req.method == "POST"
    assert json.loads(req.content) == {"reason": "rude", "reporter_id": "u1"}
    assert req.headers["prefer"] == "return=representation"
    assert req.url.params.get_list("select") == ["id,status"]


async def test_insert_upsert_sets_prefer_and_on_conflict():
    rec = Recorder([httpx.Response(201, json=[{"user_id": "u1"}])])
    await make(rec).insert(
        "surveys", {"user_id": "u1", "survey_data": {}}, auth=UserAuth("t"), upsert_on="user_id"
    )
    assert rec.last.headers["prefer"] == "resolution=merge-duplicates,return=representation"
    assert rec.last.url.params.get_list("on_conflict") == ["user_id"]


async def test_insert_with_returning_false_uses_minimal():
    rec = Recorder([httpx.Response(201)])
    result = await make(rec).insert("x", {"a": 1}, auth=ServiceAuth(), returning=False)
    assert result is None
    assert rec.last.headers["prefer"] == "return=minimal"


async def test_update_sends_patch_with_filters():
    rec = Recorder([httpx.Response(200, json=[{"id": "u1", "display_name": "S"}])])
    rows = await make(rec).update(
        "profiles",
        {"display_name": "S"},
        auth=UserAuth("t"),
        filters=[("id", "eq.u1")],
        columns="id,display_name",
    )
    assert rows == [{"id": "u1", "display_name": "S"}]
    req = rec.last
    assert req.method == "PATCH"
    assert json.loads(req.content) == {"display_name": "S"}
    assert req.url.params.get_list("id") == ["eq.u1"]
    assert req.headers["prefer"] == "return=representation"


async def test_update_and_delete_refuse_empty_filters():
    sb = make(Recorder())
    with pytest.raises(ValueError, match="filters"):
        await sb.update("profiles", {"a": 1}, auth=UserAuth("t"), filters=[])
    with pytest.raises(ValueError, match="filters"):
        await sb.delete("profiles", auth=UserAuth("t"), filters=[])


async def test_delete_sends_delete_with_minimal_return():
    rec = Recorder([httpx.Response(204)])
    assert await make(rec).delete("venues", auth=UserAuth("t"), filters=[("id", "eq.v1")]) is None
    assert rec.last.method == "DELETE"
    assert rec.last.headers["prefer"] == "return=minimal"


async def test_postgrest_error_is_raised_as_supabase_error():
    rec = Recorder(
        [
            httpx.Response(
                400, json={"code": "P0001", "message": "event_full", "details": None, "hint": "x"}
            )
        ]
    )
    with pytest.raises(SupabaseError) as info:
        await make(rec).rpc("join_event", {"p_event_id": "e"}, auth=UserAuth("t"))
    err = info.value
    assert (err.status, err.code, err.message) == (400, "P0001", "event_full")
    assert (err.details, err.hint) == (None, "x")


async def test_non_json_error_body_is_preserved_as_message():
    rec = Recorder([httpx.Response(502, text="bad gateway")])
    with pytest.raises(SupabaseError) as info:
        await make(rec).select("events", auth=UserAuth("t"))
    assert (info.value.status, info.value.code, info.value.message) == (502, None, "bad gateway")


async def test_transport_failure_is_supabase_unavailable():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(SupabaseUnavailable):
        await make(boom).select("events", auth=UserAuth("t"))


async def test_no_content_returns_none():
    rec = Recorder([httpx.Response(204)])
    assert await make(rec).rpc("leave_event", {"p_event_id": "e"}, auth=UserAuth("t")) is None
