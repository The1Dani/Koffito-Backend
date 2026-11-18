# Security

Koffito implements its own authentication and authorization; no third-party identity or data
service is involved. This page describes every mechanism and where it lives in the code.

## Overview

```
Browser (koffito-web)                         FastAPI (this repo)                    Postgres
────────────────────                          ───────────────────                    ────────
access token: in memory only   ──Bearer──▶   core/auth.py  verify HS256 JWT  ──▶  app.user_id set per
refresh token: httpOnly cookie ──cookie──▶   auth/service.py rotate / revoke        transaction; SQL
                                                                                    functions check it
```

## Accounts and passwords — `src/koffito/auth/passwords.py`

- Passwords are hashed with **Argon2id** (OWASP baseline: 19 MiB memory, 2 iterations,
  1 lane), each with its own random salt. Only the PHC hash string is stored
  (`users.password_hash`); the password is never logged or returned.
- **Policy**: 8–128 characters, not one of the ~2 000 most common passwords of 8+ characters
  (SecLists, `auth/common_passwords.txt`), not the email's local part.
- Hashes are upgraded transparently on the next login if the parameters change.
- Emails are case-insensitive (`citext`) and unique.

## Sessions — `src/koffito/core/auth.py`, `src/koffito/auth/service.py`

| | Access token | Refresh token |
| --- | --- | --- |
| Format | JWT, HS256, signed with `AUTH_JWT_SECRET` (≥ 32 chars) | 256-bit random string |
| Lifetime | 15 minutes | 30 days |
| Where the client keeps it | JavaScript memory only | `httpOnly`, `SameSite=Strict`, `Secure` (HTTPS) cookie, path `/api/auth` |
| Stored on the server | not stored | SHA-256 hash only (`refresh_tokens`) |

- Access-token checks: algorithm pinned to HS256 (`alg: none` and algorithm switching are
  refused), signature, `exp` (10 s leeway), `iss`, `aud`, `typ=access`, `sub` is a UUID. The
  token carries **no permissions**: only the user id is trusted.
- **Rotation**: every `/auth/refresh` spends the presented refresh token (one conditional
  `UPDATE`, so two concurrent requests can't both succeed) and issues a new one in the same
  *family*.
- **Reuse detection**: if an already-spent refresh token is presented again, someone holds a
  copy, so the whole family (that sign-in on every device) is revoked.
- The web client serialises refreshes across browser tabs with the Web Locks API, so a
  legitimate client never replays a token.
- **CSRF**: the cookie is `SameSite=Strict` and the cookie-based routes (`/auth/refresh`,
  `/auth/logout`) also require the header `X-Requested-With: koffito`, which a cross-site form
  or image cannot send.
- Logout revokes the family. Password change and password reset revoke **all** of the user's
  refresh tokens.

## Email verification and password reset

- Sign-up creates the account unverified; **sign-in is refused until the email is confirmed**
  (`email_not_verified`, only after the password was correct, so it reveals nothing).
- Links carry a 256-bit random single-use token. Only its SHA-256 is stored
  (`email_tokens`), with an expiry (24 h verification, 60 min reset). Issuing a new link
  invalidates older unused ones of the same kind. The web app strips the token from the
  address bar after use.
- Opening a reset link also confirms the email (it proves ownership of the mailbox).

## No account enumeration

- `/auth/register`, `/auth/forgot-password` and `/auth/resend-verification` always answer
  `202` with the same body. Email sending happens after the response, so timing is equal too.
  Registering an email that already has an account sends its owner a reset link instead.
- Wrong password and unknown email return the same `401 invalid_credentials`; for unknown
  emails a dummy Argon2 verification runs, so both take the same time.

## Abuse protection — `src/koffito/core/ratelimit.py`, `api/routes/auth.py`

- Per client IP: 20 auth requests per 5 minutes.
- Per email address: 5 emails per hour (register, resend, forgot).
- **Lockout**: 10 failed logins lock the account for 15 minutes (`account_locked`); a password
  reset clears it.
- Data routes keep their per-user limits (read / write / report / admin).
- The limiter is in memory per process; behind several replicas, plug in a shared store with
  the same `hit()` interface.

## Authorization (who may see and do what)

The backend is the **only** database client. For each request it opens a transaction and sets
`app.user_id` (transaction-local, so it can never leak into another request). SQL functions
read it with `app.uid()` and enforce the rules (`db/migrations/001_schema.sql`):

- A user reads and writes only their own profile, settings, survey and participations. Table
  writes in the repositories always filter on the id from the token, never on a body field.
  Request bodies with unknown fields are refused (`422`).
- Groupmates' profiles and the café of a blind coffee talk become visible only after
  `reveal_at` (`shares_revealed_group`, `can_see_venue`, `get_my_events`).
- Joining requires a completed survey, an open future event, free capacity and no overlapping
  coffee talk (`join_event`); ratings require having attended (`attended_event`).
- **Admin** routes depend on `require_admin`, which asks the database (`is_admin()`). The flag
  can only be changed from the server (`python -m koffito.cli make-admin`), never through the
  API.
- `tests/test_access_rules.py` checks each of these rules against a real database.

## SQL injection

`src/koffito/db/database.py`: every value is sent as a bound parameter. Table, column and
function names must match `^[a-z_][a-z0-9_]*$` and are quoted with `psycopg.sql.Identifier`.
Sort and filter operators come from a fixed list. Fixed SQL statements live in the code and
never include user input. Unit tests try injection strings against all of these.

## Transport and headers

- Production refuses to start without `ENFORCE_HTTPS=true` and explicit `TRUSTED_HOSTS`.
  HTTPS redirect and HSTS are on.
- Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
  `Referrer-Policy: no-referrer`. Auth responses are `Cache-Control: no-store`.
- Secrets (`AUTH_JWT_SECRET`, `DATABASE_URL`, SMTP password) are `SecretStr` and never appear
  in logs or error responses. Unhandled errors return a generic message.

## Tests

`uv run pytest` runs 88 tests against a real Postgres:

- `test_auth_flow.py`: every account and session flow.
- `test_access_rules.py`: the authorization rules.
- `test_security_units.py`: token forgery, password policy and injection attempts.
- `test_jobs_db.py`: the background jobs.
