"""Access tokens: issued by us (src/koffito/auth), verified here on every request.

Access tokens are short-lived JWTs signed with HS256 using `AUTH_JWT_SECRET`, a key only this
server knows. They carry no permissions: `sub` (the user id) is the only claim the API acts on,
and anything else (admin rights, data visibility) is decided by the database for that user.
"""

import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import AuthError

ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The verified caller. `id` is the token's `sub`."""

    id: UUID
    claims: Mapping[str, Any] = field(repr=False)


class TokenVerifier:
    """Issues and verifies our access tokens: signature, expiry, issuer, audience, type."""

    def __init__(
        self,
        secret: str,
        *,
        issuer: str,
        audience: str,
        ttl_seconds: int,
        leeway: int = 10,
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._ttl = ttl_seconds
        self._leeway = leeway

    def issue(self, user_id: UUID, *, now: float | None = None) -> tuple[str, int]:
        """A new access token for `user_id` and its lifetime in seconds."""
        issued_at = int(now if now is not None else time.time())
        claims = {
            "sub": str(user_id),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_at,
            "exp": issued_at + self._ttl,
            "jti": secrets.token_urlsafe(12),
            "typ": "access",
        }
        return jwt.encode(claims, self._secret, algorithm=ALGORITHM), self._ttl

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid token", code="invalid_token") from exc
        # Pin the algorithm: never let the token choose (e.g. `none` or a public-key alg).
        if header.get("alg") != ALGORITHM:
            raise AuthError("Invalid token", code="invalid_token")
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("Token expired", code="token_expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid token", code="invalid_token") from exc
        if claims.get("typ") != "access":
            raise AuthError("Invalid token", code="invalid_token")
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise AuthError("Invalid token", code="invalid_token") from exc
        return AuthenticatedUser(id=user_id, claims=claims)


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
    user = verifier.verify(credentials.credentials)
    request.state.user = user
    return user
