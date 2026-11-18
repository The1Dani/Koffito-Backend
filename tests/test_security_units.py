"""Unit tests for the security building blocks (no database needed)."""

import time
import uuid

import jwt
import pytest

from koffito.auth.opaque import new_token, token_hash
from koffito.auth.passwords import check_policy, hash_password, needs_rehash, verify_password
from koffito.core.auth import TokenVerifier
from koffito.core.errors import AuthError, UnprocessableError
from koffito.db.database import _ident, _order, _where

SECRET = "unit-secret-" + "y" * 40


def verifier(**kw) -> TokenVerifier:
    return TokenVerifier(SECRET, issuer="koffito", audience="koffito-app", ttl_seconds=900, **kw)


# --- access tokens -----------------------------------------------------------------------------


def test_issued_token_verifies_and_carries_only_the_user_id():
    uid = uuid.uuid4()
    token, ttl = verifier().issue(uid)
    user = verifier().verify(token)
    assert user.id == uid and ttl == 900
    assert set(user.claims) == {"sub", "iss", "aud", "iat", "exp", "jti", "typ"}


def test_expired_token_is_rejected_with_its_own_code():
    token, _ = verifier().issue(uuid.uuid4(), now=time.time() - 3600)
    with pytest.raises(AuthError) as exc:
        verifier().verify(token)
    assert exc.value.code == "token_expired"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: jwt.encode(c, "another-secret-" + "z" * 40, algorithm="HS256"),  # wrong key
        lambda c: jwt.encode({**c, "aud": "someone-else"}, SECRET, algorithm="HS256"),
        lambda c: jwt.encode({**c, "iss": "evil"}, SECRET, algorithm="HS256"),
        lambda c: jwt.encode({**c, "typ": "refresh"}, SECRET, algorithm="HS256"),
        lambda c: jwt.encode({**c, "sub": "not-a-uuid"}, SECRET, algorithm="HS256"),
        lambda c: jwt.encode(c, None, algorithm="none"),  # unsigned
        lambda c: "garbage.token.here",
    ],
)
def test_forged_or_foreign_tokens_are_rejected(mutate):
    token, _ = verifier().issue(uuid.uuid4())
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="koffito-app")
    with pytest.raises(AuthError) as exc:
        verifier().verify(mutate(claims))
    assert exc.value.code == "invalid_token"


# --- passwords ---------------------------------------------------------------------------------


def test_argon2id_hash_round_trip():
    h = hash_password("Flat-white-at-9")
    assert h.startswith("$argon2id$")
    assert "Flat-white-at-9" not in h
    assert verify_password(h, "Flat-white-at-9")
    assert not verify_password(h, "flat-white-at-9")
    assert not verify_password("not-a-hash", "anything")
    assert not needs_rehash(h)


def test_same_password_hashes_differently_each_time():
    assert hash_password("Cappuccino-42") != hash_password("Cappuccino-42")


@pytest.mark.parametrize(
    ("password", "email"),
    [
        ("short", None),
        ("password1", None),
        ("qwertyuiop", None),
        ("ana.maria", "ana.maria@x.com"),
        ("x" * 129, None),
    ],
)
def test_weak_passwords_are_refused(password, email):
    with pytest.raises(UnprocessableError) as exc:
        check_policy(password, email=email)
    assert exc.value.code == "weak_password"


def test_reasonable_password_passes_policy():
    check_policy("Two-flat-whites-please", email="ana@x.com")


# --- opaque tokens -----------------------------------------------------------------------------


def test_opaque_tokens_are_random_and_stored_as_hash():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 43
    assert token_hash(a) != a and len(token_hash(a)) == 64


# --- SQL building: identifiers can't carry SQL, values are always parameters ------------------


@pytest.mark.parametrize("name", ["users; drop table users", "a b", "Robert'); --", 'x"y', ""])
def test_identifiers_with_sql_are_rejected(name):
    with pytest.raises(ValueError):
        _ident(name)


def test_filter_values_become_parameters_not_sql():
    clause, params = _where([("display_name", "eq.'; drop table users; --"), ("id", "in.(a,b)")])
    rendered = clause.as_string(None)
    assert "drop table" not in rendered
    assert params == ["'; drop table users; --", ["a", "b"]]


def test_unknown_filter_operator_is_refused():
    with pytest.raises(ValueError):
        _where([("id", "like.%x%")])


def test_order_only_accepts_column_and_direction():
    assert 'order by "joined_at" asc' in _order("joined_at.asc").as_string(None)
    with pytest.raises(ValueError):
        _order("joined_at.asc; drop table users")
