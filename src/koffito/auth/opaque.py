"""Opaque random tokens (refresh tokens, email links). Only their SHA-256 is ever stored."""

import hashlib
import secrets


def new_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
