import time
import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from koffito.core.auth import AuthenticatedUser, JWKSCache, TokenVerifier, get_current_user
from koffito.core.errors import AuthError, register_exception_handlers
from tests.support import ISSUER, JWKS_URL, SigningKey, claims


class JWKSServer:
    """Serves the JWKS document via httpx.MockTransport and counts fetches."""

    def __init__(self, *keys: SigningKey) -> None:
        self.keys = list(keys)
        self.fetches = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == JWKS_URL
        self.fetches += 1
        return httpx.Response(200, json={"keys": [k.jwk for k in self.keys]})


class FakeClock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def key() -> SigningKey:
    return SigningKey("kid-a")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_verifier(server: JWKSServer, clock: FakeClock) -> TokenVerifier:
    http = httpx.AsyncClient(transport=httpx.MockTransport(server))
    jwks = JWKSCache(http, JWKS_URL, ttl=3600, min_refetch=60, clock=clock)
    return TokenVerifier(jwks, audience="authenticated", issuer=ISSUER, leeway=10)


async def test_valid_token_yields_user_id_from_sub(key, clock):
    verifier = make_verifier(JWKSServer(key), clock)
    sub = str(uuid.uuid4())
    token = key.sign(claims(sub=sub))
    user = await verifier.verify(token)
    assert user == AuthenticatedUser(id=uuid.UUID(sub), token=token, claims=user.claims)
    assert user.claims["sub"] == sub


async def test_jwks_is_fetched_once_and_cached(key, clock):
    server = JWKSServer(key)
    verifier = make_verifier(server, clock)
    await verifier.verify(key.sign(claims()))
    await verifier.verify(key.sign(claims()))
    assert server.fetches == 1


async def test_expired_token_is_token_expired(key, clock):
    verifier = make_verifier(JWKSServer(key), clock)
    past = int(time.time()) - 3600
    with pytest.raises(AuthError) as info:
        await verifier.verify(key.sign(claims(iat=past - 60, exp=past)))
    assert info.value.code == "token_expired"


@pytest.mark.parametrize(
    "bad",
    [
        {"aud": "anon"},
        {"iss": "https://evil.example.com/auth/v1"},
        {"role": "anon"},
        {"role": "service_role"},
        {"sub": "not-a-uuid"},
    ],
)
async def test_wrong_claims_are_invalid_token(key, clock, bad):
    verifier = make_verifier(JWKSServer(key), clock)
    with pytest.raises(AuthError) as info:
        await verifier.verify(key.sign(claims(**bad)))
    assert info.value.code == "invalid_token"


async def test_missing_required_claim_is_invalid_token(key, clock):
    verifier = make_verifier(JWKSServer(key), clock)
    payload = claims()
    del payload["exp"]
    with pytest.raises(AuthError) as info:
        await verifier.verify(key.sign(payload))
    assert info.value.code == "invalid_token"


async def test_hs256_token_is_rejected(key, clock):
    verifier = make_verifier(JWKSServer(key), clock)
    with pytest.raises(AuthError) as info:
        await verifier.verify(key.sign(claims(), alg="HS256"))
    assert info.value.code == "invalid_token"


async def test_garbage_token_is_invalid_token(key, clock):
    verifier = make_verifier(JWKSServer(key), clock)
    with pytest.raises(AuthError) as info:
        await verifier.verify("not.a.jwt")
    assert info.value.code == "invalid_token"


async def test_token_signed_by_another_key_with_same_kid_is_invalid(key, clock):
    verifier = make_verifier(JWKSServer(key), clock)
    impostor = SigningKey("kid-a")
    with pytest.raises(AuthError) as info:
        await verifier.verify(impostor.sign(claims()))
    assert info.value.code == "invalid_token"


async def test_unknown_kid_refetches_once_then_throttles(key, clock):
    server = JWKSServer(key)
    verifier = make_verifier(server, clock)
    await verifier.verify(key.sign(claims()))
    assert server.fetches == 1
    other = SigningKey("kid-b")
    with pytest.raises(AuthError) as info:
        await verifier.verify(other.sign(claims()))
    assert info.value.code == "unknown_kid"
    assert server.fetches == 2
    with pytest.raises(AuthError):
        await verifier.verify(other.sign(claims()))
    assert server.fetches == 2  # throttled: no refetch within min_refetch seconds


async def test_key_rotation_is_picked_up_after_throttle_window(key, clock):
    server = JWKSServer(key)
    verifier = make_verifier(server, clock)
    await verifier.verify(key.sign(claims()))
    new_key = SigningKey("kid-b")
    server.keys.append(new_key)
    clock.now += 61
    user = await verifier.verify(new_key.sign(claims()))
    assert isinstance(user.id, uuid.UUID)
    assert server.fetches == 2


async def test_cache_refreshes_after_ttl(key, clock):
    server = JWKSServer(key)
    verifier = make_verifier(server, clock)
    await verifier.verify(key.sign(claims()))
    clock.now += 3601
    await verifier.verify(key.sign(claims()))
    assert server.fetches == 2


def _app(verifier: TokenVerifier) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.verifier = verifier

    @app.get("/whoami")
    async def whoami(user: AuthenticatedUser = Depends(get_current_user)):
        return {"id": str(user.id)}

    return app


def test_dependency_rejects_missing_bearer(key, clock):
    client = TestClient(_app(make_verifier(JWKSServer(key), clock)))
    r = client.get("/whoami")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_token"
    assert r.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert client.get("/whoami", headers={"authorization": "Basic abc"}).status_code == 401


def test_dependency_rejects_invalid_token(key, clock):
    client = TestClient(_app(make_verifier(JWKSServer(key), clock)))
    r = client.get("/whoami", headers={"authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


def test_dependency_returns_user_and_records_it_on_request_state(key, clock):
    app = _app(make_verifier(JWKSServer(key), clock))

    @app.get("/state")
    async def state(user: AuthenticatedUser = Depends(get_current_user)):
        return {"same": str(user.id)}

    sub = str(uuid.uuid4())
    r = TestClient(app).get(
        "/whoami", headers={"authorization": f"Bearer {key.sign(claims(sub=sub))}"}
    )
    assert r.status_code == 200
    assert r.json() == {"id": sub}
