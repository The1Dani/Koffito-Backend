"""Sign up → confirm → sign in → refresh → sign out, and the password flows, end to end."""

from tests.conftest import Outbox, make_settings, signup, sql

PASSWORD = "Cortado-and-croissant"


def register(client, email, password=PASSWORD, name="Ana"):
    return client.post(
        "/auth/register", json={"email": email, "password": password, "first_name": name}
    )


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_stores_only_an_argon2_hash_and_creates_profile(client, outbox, clean_db):
    assert register(client, "ana@example.com").status_code == 202
    ((hash_, verified),) = sql(clean_db, "select password_hash, email_verified_at from users")
    assert hash_.startswith("$argon2id$") and PASSWORD not in hash_
    assert verified is None
    assert sql(clean_db, "select display_name from profiles") == [("Ana",)]
    assert sql(clean_db, "select count(*) from user_settings") == [(1,)]
    # the link token is only stored hashed
    token = outbox.token("ana@example.com", "verify-email")
    assert sql(clean_db, "select count(*) from email_tokens where token_hash = %s", [token]) == [
        (0,)
    ]


def test_weak_password_is_refused_before_anything_is_created(client, clean_db):
    r = register(client, "ana@example.com", password="password1")
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    assert sql(clean_db, "select count(*) from users") == [(0,)]


def test_cannot_sign_in_before_confirming_email(client):
    register(client, "ana@example.com")
    r = login(client, "ana@example.com")
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"


def test_verify_link_signs_in_and_works_once(client, outbox):
    register(client, "ana@example.com")
    token = outbox.token("ana@example.com", "verify-email")
    r = client.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/auth" in cookie
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 400


def test_duplicate_registration_looks_the_same_and_creates_nothing(client, outbox, clean_db):
    signup(client, outbox, "ana@example.com")
    r = register(client, "ANA@example.com", password="Another-good-one-9")
    assert r.status_code == 202
    assert sql(clean_db, "select count(*) from users") == [(1,)]
    # the real owner gets a reset link instead of a second account
    assert outbox.token("ana@example.com", "reset-password")


def test_wrong_password_and_unknown_email_get_the_same_answer(client, outbox):
    signup(client, outbox, "ana@example.com")
    a = login(client, "ana@example.com", "wrong-password-1")
    b = login(client, "nobody@example.com", "wrong-password-1")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_account_locks_after_repeated_failures(clean_db, outbox):
    from koffito.main import create_app
    from tests.conftest import make_client

    app = create_app(make_settings(login_max_failures=3, login_lockout_minutes=15))
    with make_client(app) as client:
        app.state.mailer.send = outbox.send
        signup(client, outbox, "ana@example.com")
        for _ in range(3):
            assert login(client, "ana@example.com", "wrong-password-1").status_code == 401
        r = login(client, "ana@example.com")  # even the right password
        assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"


def test_access_token_protects_the_api(client, outbox):
    headers = signup(client, outbox, "ana@example.com")
    assert client.get("/me", headers=headers).json()["name"] == "Ana"
    assert client.get("/me").status_code == 401
    bad = {"Authorization": headers["Authorization"][:-2] + "xx"}
    assert client.get("/me", headers=bad).status_code == 401


def test_refresh_rotates_and_a_replayed_token_ends_the_session(client, outbox):
    signup(client, outbox, "ana@example.com")
    first = client.cookies.get("koffito_refresh")
    r = client.post("/auth/refresh", cookies={"koffito_refresh": first})
    assert r.status_code == 200
    second = r.cookies.get("koffito_refresh")
    assert second and second != first
    # someone replays the old token → that whole sign-in is revoked
    assert client.post("/auth/refresh", cookies={"koffito_refresh": first}).status_code == 401
    assert client.post("/auth/refresh", cookies={"koffito_refresh": second}).status_code == 401


def test_refresh_requires_the_csrf_header(client, outbox):
    signup(client, outbox, "ana@example.com")
    cookie = client.cookies.get("koffito_refresh")
    r = client.post(
        "/auth/refresh", cookies={"koffito_refresh": cookie}, headers={"X-Requested-With": ""}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_header_missing"


def test_logout_revokes_the_refresh_token(client, outbox):
    signup(client, outbox, "ana@example.com")
    cookie = client.cookies.get("koffito_refresh")
    assert client.post("/auth/logout", cookies={"koffito_refresh": cookie}).status_code == 204
    assert client.post("/auth/refresh", cookies={"koffito_refresh": cookie}).status_code == 401


def test_forgot_password_never_reveals_accounts(client, outbox):
    signup(client, outbox, "ana@example.com")
    sent_before = len(outbox.mails)
    assert (
        client.post("/auth/forgot-password", json={"email": "nobody@example.com"}).status_code
        == 202
    )
    assert len(outbox.mails) == sent_before
    assert (
        client.post("/auth/forgot-password", json={"email": "ana@example.com"}).status_code == 202
    )
    assert outbox.token("ana@example.com", "reset-password")


def test_reset_password_changes_it_and_signs_out_everywhere(client, outbox):
    signup(client, outbox, "ana@example.com")
    session = client.cookies.get("koffito_refresh")
    client.post("/auth/forgot-password", json={"email": "ana@example.com"})
    token = outbox.token("ana@example.com", "reset-password")
    assert (
        client.post(
            "/auth/reset-password", json={"token": token, "password": "New-espresso-77"}
        ).status_code
        == 204
    )
    assert client.post("/auth/refresh", cookies={"koffito_refresh": session}).status_code == 401
    assert login(client, "ana@example.com").status_code == 401
    assert login(client, "ana@example.com", "New-espresso-77").status_code == 200
    # the link is single-use
    assert (
        client.post(
            "/auth/reset-password", json={"token": token, "password": "Another-espresso-8"}
        ).status_code
        == 400
    )


def test_change_password_needs_the_current_one(client, outbox):
    headers = signup(client, outbox, "ana@example.com")
    r = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "wrong-password-1", "new_password": "Brand-new-mocha-3"},
    )
    assert r.status_code == 401
    r = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "Brand-new-mocha-3"},
    )
    assert r.status_code == 200
    assert login(client, "ana@example.com", "Brand-new-mocha-3").status_code == 200


def test_resend_verification_only_for_unconfirmed_accounts(client, outbox: Outbox):
    register(client, "ana@example.com")
    before = len(outbox.mails)
    client.post("/auth/resend-verification", json={"email": "ana@example.com"})
    assert len(outbox.mails) == before + 1
    old = outbox.mails[before - 1].link.split("token=")[1]
    # the previous link stopped working
    assert client.post("/auth/verify-email", json={"token": old}).status_code == 400
