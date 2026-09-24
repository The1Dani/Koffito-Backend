import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import AuthError

logger = logging.getLogger(__name__)

ALGORITHM = "ES256"  # Supabase signs access tokens with the project's asymmetric signing key


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The verified caller. `id` is the JWT `sub`; `token` is forwarded to PostgREST."""

    id: UUID
    token: str
    claims: Mapping[str, Any]


class JWKSCache:
    """Fetches and caches the project's JSON Web Key Set.

    Keys are re-fetched when the cache is older than `ttl`, or when a token names an unknown
    `kid` (key rotation) — but at most once every `min_refetch` seconds, so a flood of tokens
    with bogus kids cannot turn into a flood of JWKS requests.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        ttl: float = 3600.0,
        min_refetch: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._url = url
        self._ttl = ttl
        self._min_refetch = min_refetch
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_miss_refetch: float | None = None
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        async with self._lock:
            await self._fetch()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        if not self._stale() and kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            if self._stale():
                await self._fetch()
            elif kid not in self._keys and self._may_refetch_on_miss():
                self._last_miss_refetch = self._clock()
                await self._fetch()
        if kid in self._keys:
            return self._keys[kid]
        raise AuthError("Unknown signing key", code="unknown_kid")

    def _stale(self) -> bool:
        return self._fetched_at is None or self._clock() - self._fetched_at >= self._ttl

    def _may_refetch_on_miss(self) -> bool:
        return (
            self._last_miss_refetch is None
            or self._clock() - self._last_miss_refetch >= self._min_refetch
        )

    async def _fetch(self) -> None:
        response = await self._http.get(self._url)
        response.raise_for_status()
        keys: dict[str, jwt.PyJWK] = {}
        for entry in response.json().get("keys", []):
            kid = entry.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = jwt.PyJWK.from_dict(entry)
            except jwt.PyJWKError:
                logger.warning("skipping unusable JWK kid=%s", kid)
        self._keys = keys
        self._fetched_at = self._clock()


class TokenVerifier:
    """Verifies a Supabase access token: signature (JWKS), expiry, audience, issuer, role."""

    def __init__(self, jwks: JWKSCache, *, audience: str, issuer: str, leeway: int = 10) -> None:
        self._jwks = jwks
        self._audience = audience
        self._issuer = issuer
        self._leeway = leeway

    async def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid token", code="invalid_token") from exc
        kid = header.get("kid")
        if header.get("alg") != ALGORITHM or not kid:
            raise AuthError("Invalid token", code="invalid_token")
        key = await self._jwks.get_key(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("Token expired", code="token_expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid token", code="invalid_token") from exc
        # anon and service-role tokens are valid Supabase JWTs but are never a signed-in user.
        if claims.get("role") != "authenticated":
            raise AuthError("Invalid token", code="invalid_token")
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise AuthError("Invalid token", code="invalid_token") from exc
        return AuthenticatedUser(id=user_id, token=token, claims=claims)


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency: the verified user behind `Authorization: Bearer <token>`.

    The user id only ever comes from here — never from a request body or query string.
    """
    if credentials is None or not credentials.credentials:
        raise AuthError("Missing bearer token", code="missing_token")
    verifier: TokenVerifier = request.app.state.verifier
    user = await verifier.verify(credentials.credentials)
    request.state.user = user
    return user
