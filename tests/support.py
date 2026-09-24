"""Test doubles shared across the suite: an ES256 signing key and a fake Supabase backend."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

SUPABASE_URL = "https://test.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
JWKS_PATH = "/auth/v1/.well-known/jwks.json"
JWKS_URL = f"{SUPABASE_URL}{JWKS_PATH}"
REST = "/rest/v1"

Responder = httpx.Response | Callable[[httpx.Request], httpx.Response]


class SigningKey:
    """A P-256 key pair that signs tokens the way Supabase Auth does (ES256 + kid header)."""

    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.pem = self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public = jwt.algorithms.ECAlgorithm.to_jwk(self.private.public_key(), as_dict=True)
        self.jwk = {**public, "kid": kid, "alg": "ES256", "use": "sig"}

    def sign(self, claims: dict[str, Any], *, alg: str = "ES256", kid: str | None = None) -> str:
        headers = {"kid": kid or self.kid}
        if alg == "ES256":
            return jwt.encode(claims, self.pem, algorithm="ES256", headers=headers)
        secret = "shared-secret-for-tests-0123456789ab"  # >= 32 bytes: no PyJWT warning
        return jwt.encode(claims, secret, algorithm=alg, headers=headers)


def claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    base = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": str(uuid.uuid4()),
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return {**base, **overrides}


class FakeBackend:
    """`httpx.MockTransport` handler standing in for Supabase.

    Serves the JWKS document for the signing keys it was given, records every PostgREST
    request, and answers them from scripted responses: `on(method, path, ...)` queues one-shot
    responses, `always(method, path, response)` sets a standing one; the default is `200 []`.
    """

    def __init__(self, *keys: SigningKey, jwks_status: int = 200) -> None:
        self.keys = list(keys)
        self.jwks_status = jwks_status
        self.jwks_fetches = 0
        self.requests: list[httpx.Request] = []
        self._scripted: dict[tuple[str, str], list[Responder]] = {}
        self._always: dict[tuple[str, str], Responder] = {}

    def on(self, method: str, path: str, *responders: Responder) -> FakeBackend:
        self._scripted.setdefault((method.upper(), f"{REST}{path}"), []).extend(responders)
        return self

    def always(self, method: str, path: str, responder: Responder) -> FakeBackend:
        self._always[(method.upper(), f"{REST}{path}")] = responder
        return self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == JWKS_PATH:
            self.jwks_fetches += 1
            if self.jwks_status != 200:
                return httpx.Response(self.jwks_status, text="jwks unavailable")
            return httpx.Response(200, json={"keys": [k.jwk for k in self.keys]})
        self.requests.append(request)
        key = (request.method, request.url.path)
        queue = self._scripted.get(key)
        responder = queue.pop(0) if queue else self._always.get(key)
        if responder is None:
            return httpx.Response(200, json=[])
        return responder(request) if callable(responder) else responder

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [
            r for r in self.requests if r.method == method.upper() and r.url.path == f"{REST}{path}"
        ]
