import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request, Response

from .errors import RateLimitedError


@dataclass(frozen=True, slots=True)
class RateLimit:
    limit: int
    window: float  # seconds
    scope: str  # keeps counters of different route groups apart


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after: float
    remaining: int


class Limiter(Protocol):
    def hit(self, key: str, rl: RateLimit) -> Decision: ...


class SlidingWindowLimiter:
    """In-memory sliding-window limiter: one deque of hit timestamps per key.

    Per process only. Behind several replicas swap in a Redis-backed `Limiter` (same `hit`
    contract) in the app lifespan; nothing else changes.
    """

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, prune_every: int = 1000
    ) -> None:
        self._clock = clock
        self._prune_every = prune_every
        self._hits: dict[str, deque[float]] = {}
        self._ops = 0

    def hit(self, key: str, rl: RateLimit) -> Decision:
        now = self._clock()
        window = self._hits.setdefault(key, deque())
        cutoff = now - rl.window
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= rl.limit:
            return Decision(False, window[0] + rl.window - now, 0)
        window.append(now)
        self._ops += 1
        if self._ops % self._prune_every == 0:
            self._prune(now)
        return Decision(True, 0.0, rl.limit - len(window))

    def _prune(self, now: float) -> None:
        # Drop keys whose newest hit is older than any window we could reasonably be asked about.
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] > 3600]
        for k in stale:
            del self._hits[k]


def rate_limited(
    rl: RateLimit | Callable[[Any], RateLimit],
) -> Callable[[Request, Response], Awaitable[None]]:
    """Build a FastAPI dependency enforcing `rl` per user (or per client IP before auth).

    `rl` may be a callable taking the app settings, so presets can be derived from config.
    """

    async def dependency(request: Request, response: Response) -> None:
        settings = request.app.state.settings
        if not settings.rate_limit_enabled:
            return
        limit = rl(settings) if callable(rl) else rl
        user = getattr(request.state, "user", None)
        if user is not None:
            key = f"{limit.scope}:u:{user.id}"
        else:
            host = request.client.host if request.client else "unknown"
            key = f"{limit.scope}:ip:{host}"
        decision = request.app.state.limiter.hit(key, limit)
        if not decision.allowed:
            raise RateLimitedError(retry_after=decision.retry_after)
        response.headers["X-RateLimit-Limit"] = str(limit.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)

    return dependency
