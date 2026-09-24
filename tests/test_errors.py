from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from koffito.core.errors import (
    AppError,
    AuthError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    register_exception_handlers,
)


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    class Body(BaseModel):
        name: str

    @app.get("/app-error")
    async def app_error():
        raise ConflictError("event is full", code="event_full", details={"event_id": "x"})

    @app.get("/auth-error")
    async def auth_error():
        raise AuthError("token expired", code="token_expired")

    @app.get("/forbidden")
    async def forbidden():
        raise ForbiddenError("admins only", code="admin_required")

    @app.get("/not-found")
    async def not_found():
        raise NotFoundError("no such profile", code="profile_not_found")

    @app.get("/rate-limited")
    async def rate_limited():
        raise RateLimitedError(retry_after=7)

    @app.post("/validate")
    async def validate(body: Body):
        return body

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    return app


def test_app_error_uses_envelope_status_and_code():
    client = TestClient(_app())
    r = client.get("/app-error")
    assert r.status_code == 409
    assert r.json() == {
        "error": {"code": "event_full", "message": "event is full", "details": {"event_id": "x"}}
    }


def test_auth_error_sets_www_authenticate_header():
    r = TestClient(_app()).get("/auth-error")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert r.json()["error"]["code"] == "token_expired"


def test_forbidden_and_not_found_codes():
    client = TestClient(_app())
    assert client.get("/forbidden").json()["error"]["code"] == "admin_required"
    assert client.get("/forbidden").status_code == 403
    assert client.get("/not-found").json()["error"]["code"] == "profile_not_found"
    assert client.get("/not-found").status_code == 404


def test_rate_limited_sets_retry_after():
    r = TestClient(_app()).get("/rate-limited")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "7"
    assert r.json()["error"]["code"] == "rate_limited"


def test_unknown_route_uses_envelope():
    r = TestClient(_app()).get("/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_validation_error_is_422_without_leaking_input():
    r = TestClient(_app()).post("/validate", json={"name": 123, "secret": "leak"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"] == [
        {"loc": ["body", "name"], "msg": "Input should be a valid string", "type": "string_type"}
    ]
    assert "leak" not in r.text


def test_unhandled_exception_is_masked():
    r = TestClient(_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "Internal server error"}}
    assert "secret internal detail" not in r.text


def test_app_error_defaults():
    err = AppError("boom")
    assert (err.status_code, err.code, err.message, err.details, err.headers) == (
        500,
        "internal_error",
        "boom",
        None,
        None,
    )
