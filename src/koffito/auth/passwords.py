"""Password hashing (Argon2id) and the password policy."""

from functools import lru_cache
from importlib.resources import files

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..core.errors import UnprocessableError

MIN_LENGTH = 8
MAX_LENGTH = 128  # bounds the hashing cost per request

# OWASP's recommended Argon2id baseline (m=19 MiB, t=2, p=1).
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)

# Hashed once at import: verifying against it for unknown emails keeps login timing the same
# whether or not the account exists.
DUMMY_HASH = _hasher.hash("koffito-timing-equaliser")


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    text = files("koffito.auth").joinpath("common_passwords.txt").read_text(encoding="utf-8")
    return frozenset(line for line in text.splitlines() if line and not line.startswith("#"))


def check_policy(password: str, *, email: str | None = None) -> None:
    """Raise a 422 with a user-facing message when `password` is too weak."""
    if len(password) < MIN_LENGTH:
        raise UnprocessableError(f"Use at least {MIN_LENGTH} characters", code="weak_password")
    if len(password) > MAX_LENGTH:
        raise UnprocessableError(f"Use at most {MAX_LENGTH} characters", code="weak_password")
    lowered = password.lower()
    if lowered in _common_passwords():
        raise UnprocessableError(
            "That password is too common. Pick something less guessable.", code="weak_password"
        )
    if email and lowered == email.lower().split("@")[0]:
        raise UnprocessableError("Don't use your email as your password", code="weak_password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash uses older parameters; rehash on the next successful login."""
    return _hasher.check_needs_rehash(password_hash)
