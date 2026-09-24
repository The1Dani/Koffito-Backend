import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from koffito.api.deps import require_admin
from koffito.core.config import Settings
from koffito.core.ratelimit import SlidingWindowLimiter
from koffito.main import create_app
from koffito.supabase import SupabaseError, SupabaseRest
from tests.support import SUPABASE_URL, FakeBackend


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["environment"] == "development"
    assert isinstance(body["version"], str)
    assert client.get("/").json()["status"] == "ok"


def test_lifespan_warms_jwks_and_builds_shared_state(app, backend, settings):
    with TestClient(app):
        assert backend.jwks_fetches == 1
        assert app.state.settings is settings
        assert isinstance(app.state.supabase, SupabaseRest)
        assert isinstance(app.state.limiter, SlidingWindowLimiter)


def test_jwks_failure_at_startup_only_warns_in_development(signing_key):
    backend = FakeBackend(signing_key, jwks_status=503)
    settings = Settings(
        supabase_url=SUPABASE_URL,
        supabase_publishable_key="pub-key",
        koffito_backend_key="bk",
        _env_file=None,
    )
    app = create_app(settings, transport=httpx.MockTransport(backend))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_jwks_failure_at_startup_fails_fast_in_production(signing_key):
    backend = FakeBackend(signing_key, jwks_status=503)
    settings = Settings(
        supabase_url=SUPABASE_URL,
        supabase_publishable_key="pub-key",
        koffito_backend_key="bk",
        environment="production",
        enforce_https=True,
        trusted_hosts="api.koffito.test",
        _env_file=None,
    )
    app = create_app(settings, transport=httpx.MockTransport(backend))
    with pytest.raises(httpx.HTTPStatusError), TestClient(app):
        pass


def test_jobs_enabled_requires_service_key(signing_key):
    settings = Settings(
        supabase_url=SUPABASE_URL,
        supabase_publishable_key="pub-key",
        koffito_backend_key="bk",
        jobs_enabled=True,
        _env_file=None,
    )
    app = create_app(settings, transport=httpx.MockTransport(FakeBackend(signing_key)))
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY"), TestClient(app):
        pass


def test_supabase_errors_are_rendered_with_the_envelope(app):
    @app.get("/_boom")
    async def boom():
        raise SupabaseError(400, "P0001", "event_full")

    with TestClient(app) as client:
        r = client.get("/_boom")
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "event_full", "message": "event full"}}


def test_require_admin_asks_supabase_with_the_users_token(app, backend, auth, token):
    @app.get("/_admin", dependencies=[Depends(require_admin)])
    async def admin_only():
        return {"ok": True}

    backend.on("POST", "/rpc/is_admin", httpx.Response(200, json=True))
    with TestClient(app) as client:
        r = client.get("/_admin", headers=auth)
    assert r.status_code == 200
    call = backend.calls("POST", "/rpc/is_admin")[0]
    assert call.headers["authorization"] == f"Bearer {token}"
    assert call.headers["apikey"] == "pub-key"
    assert call.headers["x-koffito-backend-key"] == "backend-key"


def test_require_admin_rejects_non_admins(app, backend, auth):
    @app.get("/_admin", dependencies=[Depends(require_admin)])
    async def admin_only():
        return {"ok": True}

    backend.on("POST", "/rpc/is_admin", httpx.Response(200, json=False))
    with TestClient(app) as client:
        r = client.get("/_admin", headers=auth)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "admin_required"


def test_require_admin_requires_a_token(app):
    @app.get("/_admin", dependencies=[Depends(require_admin)])
    async def admin_only():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/_admin").status_code == 401
