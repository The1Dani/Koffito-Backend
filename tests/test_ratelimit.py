from types import SimpleNamespace

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from koffito.core.errors import register_exception_handlers
from koffito.core.ratelimit import RateLimit, SlidingWindowLimiter, rate_limited


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_up_to_limit_then_rejects_with_retry_after():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    rl = RateLimit(limit=3, window=60, scope="t")
    assert [limiter.hit("k", rl).allowed for _ in range(3)] == [True, True, True]
    decision = limiter.hit("k", rl)
    assert decision.allowed is False
    assert decision.remaining == 0
    assert 0 < decision.retry_after <= 60


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    rl = RateLimit(limit=2, window=10, scope="t")
    limiter.hit("k", rl)
    clock.now += 6
    limiter.hit("k", rl)
    assert limiter.hit("k", rl).allowed is False
    clock.now += 5  # first hit is now 11s old -> outside the window
    assert limiter.hit("k", rl).allowed is True


def test_limiter_keys_are_independent():
    limiter = SlidingWindowLimiter(clock=FakeClock())
    rl = RateLimit(limit=1, window=60, scope="t")
    assert limiter.hit("a", rl).allowed is True
    assert limiter.hit("b", rl).allowed is True
    assert limiter.hit("a", rl).allowed is False


def _app(enabled: bool = True) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.settings = SimpleNamespace(rate_limit_enabled=enabled)
    app.state.limiter = SlidingWindowLimiter(clock=FakeClock())

    async def fake_user(request: Request) -> None:
        if user := request.headers.get("x-test-user"):
            request.state.user = SimpleNamespace(id=user)

    limit = RateLimit(limit=2, window=60, scope="test")

    @app.get("/thing", dependencies=[Depends(fake_user), Depends(rate_limited(limit))])
    async def thing():
        return {"ok": True}

    return app


def test_dependency_limits_per_user_and_reports_headers():
    client = TestClient(_app())
    r1 = client.get("/thing", headers={"x-test-user": "u1"})
    assert r1.status_code == 200
    assert r1.headers["x-ratelimit-limit"] == "2"
    assert r1.headers["x-ratelimit-remaining"] == "1"
    client.get("/thing", headers={"x-test-user": "u1"})
    r3 = client.get("/thing", headers={"x-test-user": "u1"})
    assert r3.status_code == 429
    assert r3.json()["error"]["code"] == "rate_limited"
    assert int(r3.headers["retry-after"]) >= 1
    # another user is unaffected
    assert client.get("/thing", headers={"x-test-user": "u2"}).status_code == 200


def test_dependency_falls_back_to_client_ip_without_user():
    client = TestClient(_app())
    assert client.get("/thing").status_code == 200
    assert client.get("/thing").status_code == 200
    assert client.get("/thing").status_code == 429


def test_dependency_is_noop_when_disabled():
    client = TestClient(_app(enabled=False))
    for _ in range(5):
        assert client.get("/thing", headers={"x-test-user": "u1"}).status_code == 200
