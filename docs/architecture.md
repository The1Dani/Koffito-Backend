# Architecture

## Request flow

```
App ── POST /auth/login ─────────────▶ api/routes/auth.py ─▶ auth/service.py ─┐
    ◀─ access token + refresh cookie ─                                         │
                                                                               ▼
App ── Authorization: Bearer <token> ▶ core/auth.get_current_user ─▶ router ─▶ service
                                       (verify HS256 JWT)                        │
                                                                                 ▼
                                                 repository ─▶ db/database.Database
                                                               (psycopg pool; one transaction
                                                                per call, app.user_id set)
                                                                                 │
                                                                                 ▼
                                                       Postgres: SQL functions + tables
```

## Layers

```
api/routes/*.py      routers: validate input (schemas), call a service, declare response models
api/routes/auth.py   /auth/*: cookie handling, CSRF header, per-IP / per-email limits, email
api/deps.py          wiring: settings, shared Database, get_current_user, require_admin,
                     rate-limit presets (READ / WRITE / REPORT / ADMIN), service factories
auth/                our auth: service (accounts, sessions, links), passwords (Argon2id +
                     policy), opaque (random tokens + hashes), mailer (SMTP, Koffito-styled)
services/*.py        one service per resource; owns the user's AuthenticatedUser and turns
                     "no rows" / SQL errors into the API's own errors
repositories/*.py    thin: the exact query (table, columns, filters) or SQL function call;
                     repositories/rpc.py lists every SQL function the backend calls
db/database.py       Database: async pool, rpc/select/insert/update/delete/fetch, bound
                     parameters only, validated identifiers, app.user_id per transaction
db/errors.py         DatabaseError + mapping to the error envelope (RPC names, SQLSTATEs)
core/                config (pydantic-settings), auth (access-token verifier), errors
                     (envelope + handlers), ratelimit, logging
jobs/                background jobs and their runner / CLI
migrate.py, cli.py   schema migrations; make-admin / seed
```

Rules: routers never touch `Database` directly; services never build SQL; repositories never
raise API errors. Every `__init__.py` re-exports with a sorted `__all__`.

## App factory and lifespan

`main.create_app(settings=None, *, db=None)` builds the app. The lifespan opens the database pool,
builds the `TokenVerifier`, `Mailer`, `AuthService` and the limiter on `app.state`, and — with
`JOBS_ENABLED=true` — starts the job loop. A middleware adds security headers. `koffito/asgi.py`
exposes `app = create_app()` for uvicorn; `uv run koffito` runs it with reload.

## Authentication

See [security.md](security.md) for the full design. In short: `/auth/login` (or
`/auth/verify-email`) returns a 15-minute HS256 access token and sets a rotating 30-day refresh
token in an httpOnly cookie. `core/auth.get_current_user` verifies the access token on every
data route (`401 missing_token | invalid_token | token_expired`, with
`WWW-Authenticate: Bearer`). The app refreshes once and retries. `require_admin` asks the
database (`is_admin()`); nothing in the token is trusted for authorization.

## Errors

One envelope everywhere: `{"error": {"code", "message", "details"?}}`. `core/errors.py`
defines the `AppError` family and handlers (including 422 validation and masked 500s).
`db/errors.py` maps database failures:
- `raise exception '<name>'` in a SQL function becomes a stable `code` (`event_full` → 409,
  `invalid_stage` → 422, `not_admin` → 403 …).
- SQLSTATEs map to 409 / 422, a missing single row maps to 404, and an unreachable database
  maps to 503.

## Rate limiting

`core/ratelimit.py` is an in-memory sliding window keyed by user id (IP before auth), applied
as a dependency with presets from settings; the auth routes add a per-email limit. It is per
process: run one uvicorn worker per container and scale by replicas, or plug a shared
`Limiter` into `app.state.limiter`.

## Background jobs

`jobs/` runs with `ServiceAuth()` (no user). They run in this order:
- `matchmaking.py` (v1) chunks an open event's `joined` participants, in join order, into
  groups of `target_group_size`, creates the groups and marks participants and event
  `matched`.
- `venues.py` (v1) gives a venue-less group the largest active café that seats it.
- `reminders.py` notifies participants whose event starts within 24 h / 3 h, through a
  `Notifier` (`LoggingNotifier` until push or email reminders are wired up). It stamps
  `reminded_*_at` with an `is null` guard.
- `completion.py` marks events `completed` two hours after they start.

`runner.py` runs them every `JOBS_INTERVAL_SECONDS`. `python -m koffito.jobs <name|all> [--loop]`
is the one-shot or cron entry point, and `compose.yaml` runs it as the `jobs` service.

## Adding a resource

1. Schemas in `schemas/<x>.py` (`StrictModel` for bodies), export from `schemas/__init__.py`.
2. SQL in a new `db/migrations/NNN_*.sql` if needed (functions keyed on `app.uid()`).
3. A repository method (or an RPC in `repositories/rpc.py`).
4. A service in `services/<x>.py` taking `(db, user)`; scope user-owned rows to `user.id`.
5. A factory in `api/deps.py`, a router in `api/routes/<x>.py` with
   `dependencies=[Depends(get_current_user)]` (or `require_admin`) and a rate-limit preset,
   registered in `main.py`.
6. Tests against the real database (`tests/test_access_rules.py` style), then document it in
   `docs/frontend-integration.md`.
