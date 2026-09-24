# Architecture

## Request flow

```
Expo app ── Authorization: Bearer <supabase access token> ──▶ FastAPI
                                                              │
                              core/auth.get_current_user ─────┤ 1. verify JWT (JWKS, ES256,
                                                              │    exp, aud, iss, role)
                              api/deps.require_admin ─────────┤ 2. (admin routes) rpc/is_admin
                                                              │    with the user's token
                              core/ratelimit ─────────────────┤ 3. per-user sliding window
                                                              │
                              routes → services → repositories│ 4. business call
                                                              ▼
                              supabase/client.SupabaseRest ── PostgREST (/rest/v1)
                                 UserAuth(token):  apikey=<publishable>, Bearer <user token>
                                 ServiceAuth():    apikey=<service key>          (jobs only)
                                 always:           X-Koffito-Backend-Key: <gate key>
                                                              │
                                                              ▼
                                                      Postgres: RLS + SQL functions
```

The API never stores tokens; each request is verified on its own. The user id is always the
JWT `sub` — request bodies reject any `user_id`-like field (`extra="forbid"`).

## Layers

```
api/routes/*.py      routers: validate input (schemas), call a service, declare response models
api/deps.py          wiring: settings, shared SupabaseRest, get_current_user, require_admin,
                     rate-limit presets (READ / WRITE / REPORT / ADMIN), service factories
services/*.py        one service per resource; owns the user's AuthenticatedUser and turns
                     "no rows" / PostgREST codes into the API's own errors
repositories/*.py    thin: build the exact PostgREST call (table, columns, filters, Prefer);
                     repositories/rpc.py lists every SQL function the backend calls
supabase/client.py   SupabaseRest: shared httpx.AsyncClient, header rules, error parsing
supabase/errors.py   SupabaseError + mapping to the error envelope (RPC names, SQLSTATEs)
core/                config (pydantic-settings), auth (JWKS cache + verifier), errors
                     (envelope + handlers), ratelimit, logging
jobs/                service-role background jobs and their runner / CLI
```

Rules: routers never touch `SupabaseRest` directly; services never build query strings;
repositories never raise API errors. Every `__init__.py` re-exports with a sorted `__all__`.

## App factory and lifespan

`main.create_app(settings=None, *, transport=None)` builds the app. The lifespan creates the
one `httpx.AsyncClient`, warms the JWKS cache (a failure only warns in development and fails
fast in production), builds `TokenVerifier`, `SupabaseRest` and the limiter on `app.state`,
and — with `JOBS_ENABLED=true` — starts the job loop. `koffito/asgi.py` exposes
`app = create_app()` for uvicorn; `uv run koffito` runs it with reload.

Tests pass a `transport` so the same client talks to an in-memory fake Supabase
(`tests/support.FakeBackend`), which serves the JWKS for a test signing key and records every
PostgREST request — route tests assert the exact call the backend makes.

## Authentication

`core/auth.py`:

- `JWKSCache` fetches `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`, re-fetches after
  `JWKS_CACHE_TTL_SECONDS` or when a token names an unknown `kid` (throttled by
  `JWKS_MIN_REFETCH_SECONDS`).
- `TokenVerifier.verify()` requires `alg=ES256` + `kid`, checks signature, `exp`/`iat`/`sub`,
  `aud=authenticated`, `iss=<SUPABASE_URL>/auth/v1` and `role=authenticated` (anon and
  service tokens are not users). Failures are `401` with codes `missing_token`,
  `invalid_token`, `token_expired`, `unknown_kid` and a `WWW-Authenticate: Bearer` header;
  the app refreshes once and retries.
- `require_admin` (in `api/deps.py`) calls the SQL function `is_admin()` with the user's
  token. Nothing in the JWT is trusted for authorization.

## Errors

One envelope everywhere: `{"error": {"code", "message", "details"?}}`. `core/errors.py`
defines the `AppError` family and handlers (including 422 validation and masked 500s);
`supabase/errors.py` maps PostgREST failures: `raise exception '<name>'` in an RPC becomes a
stable `code` (`event_full` → 409, `invalid_stage` → 422, `not_admin` → 403 …), SQLSTATEs map
to 409/422, `PGRST116` → 404, and the gate's `42501` → 500 `backend_misconfigured` (the
backend key is wrong or was rotated).

## Rate limiting

`core/ratelimit.py` is an in-memory sliding window keyed by user id (IP before auth), applied
as a dependency with presets from settings. It is per process: run one uvicorn worker per
container and scale by replicas, or plug a Redis-backed `Limiter` into `app.state.limiter`.

## Background jobs

`jobs/` runs with `ServiceAuth()` only. `reminders.py` finds participants whose event starts
within 24 h / 3 h, notifies them through a `Notifier` (`LoggingNotifier` until push is wired
up) and stamps `reminded_24h_at` / `reminded_3h_at` with an `is.null` guard so overlapping
runners never double-stamp. `matchmaking.py` and `venues.py` contain the reads and intended
writes with the algorithm left as a TODO. `runner.py` runs them sequentially every
`JOBS_INTERVAL_SECONDS`; `python -m koffito.jobs <name|all> [--loop]` is the one-shot / cron
entry point for multi-replica deployments.

## Adding a resource

1. Schemas in `schemas/<x>.py` (`StrictModel` for bodies), export from `schemas/__init__.py`.
2. A repository method (or an RPC in `repositories/rpc.py`) building the PostgREST call.
3. A service in `services/<x>.py` taking `(sb, user)`; raise `NotFoundError` etc. there.
4. A factory in `api/deps.py`, a router in `api/routes/<x>.py` with `dependencies=[Depends(get_current_user)]`
   (or `require_admin`) and a rate-limit preset, registered in `main.py`.
5. Tests in `tests/test_routes_<x>.py` asserting the recorded PostgREST call and error mapping.
6. Document it in `docs/frontend-integration.md`.
