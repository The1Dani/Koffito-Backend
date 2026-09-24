# Development

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | 0.12.x | dependencies, virtualenv, running commands (downloads Python for you) |
| Python | 3.14.7 exactly | `requires-python = "==3.14.7"` |
| Docker + Compose | any recent | only for the container workflow |

## Configuration

Copy `.env.example` to `.env` and fill it in. `.env` is git-ignored; every value can also be
a real environment variable.

| Variable | Required | Meaning |
| --- | --- | --- |
| `SUPABASE_URL` | yes | `https://<ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | yes | publishable (or legacy anon) key — public, the app ships the same one |
| `KOFFITO_BACKEND_KEY` | yes | plaintext gate key from `select private.rotate_backend_key();` |
| `SUPABASE_SERVICE_ROLE_KEY` | for jobs | service-role or `sb_secret_…` key; never used for user requests |
| `JOBS_ENABLED`, `JOBS_INTERVAL_SECONDS` | no | run the job loop inside this process (one instance only) |
| `RATE_LIMIT_*` | no | per-user limits; `RATE_LIMIT_ENABLED=false` switches them off |
| `ENVIRONMENT`, `ENFORCE_HTTPS`, `TRUSTED_HOSTS`, `CORS_ORIGINS`, `LOG_LEVEL` | no | deployment; production requires `ENFORCE_HTTPS=true` and explicit `TRUSTED_HOSTS` |
| `JWT_*`, `JWKS_*`, `SUPABASE_TIMEOUT_SECONDS` | no | verification tuning; defaults fit Supabase |

The settings model is `src/koffito/core/config.py`.

## Run

```bash
uv sync                      # creates .venv with the exact lockfile
uv run koffito               # uvicorn with reload on 127.0.0.1:8000
# or
uv run uvicorn koffito.asgi:app --reload
```

Swagger UI: <http://127.0.0.1:8000/docs>. Smoke test:

```bash
curl -s localhost:8000/health
curl -i localhost:8000/me                       # 401 with the error envelope
curl -s localhost:8000/me -H "authorization: Bearer $TOKEN" | jq
```

Getting a token for manual testing (email confirmation is on, so use an existing account):

```bash
TOKEN=$(curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_PUBLISHABLE_KEY" -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"…"}' | jq -r .access_token)
```

## Tests and lint

```bash
uv run pytest                              # unit + route tests against an in-memory fake Supabase
uv run ruff check . && uv run ruff format --check .
```

Route tests run the real app against `tests/support.FakeBackend` through `httpx.MockTransport`:
it serves the JWKS for a test signing key (`SigningKey`), answers PostgREST calls from scripted
responses (`backend.on(...)` / `backend.always(...)`) and records every request, so tests assert
the exact table / RPC, filters, `Prefer` header and that the user id came from the token.

Live checks against the real project (opt-in, needs `.env` and a confirmed test account):

```bash
KOFFITO_INTEGRATION=1 KOFFITO_TEST_EMAIL=… KOFFITO_TEST_PASSWORD=… uv run pytest tests/test_integration.py
```

End-to-end scripts that drive a running local API (`uv run koffito`) with throwaway users
created through the Supabase admin API (needs `SUPABASE_SERVICE_ROLE_KEY` in `.env`; they
clean up after themselves):

```bash
scripts/e2e-user.sh     # gate, /me, survey, join/confirm/reveal/rating/leave, reports, non-admin 403
scripts/e2e-admin.sh    # admin events/venues/reports, reminder send + stamp, jobs skeletons
```

## Background jobs

```bash
uv run python -m koffito.jobs reminders          # one shot
uv run python -m koffito.jobs all --loop         # every JOBS_INTERVAL_SECONDS
```

Needs `SUPABASE_SERVICE_ROLE_KEY`. In-process (`JOBS_ENABLED=true`) is the single-instance
convenience; with several replicas run the CLI from one cron / one container instead.

## Docker

```bash
docker build -t koffito .
docker run --rm --env-file .env -p 8000:8000 koffito
# or
docker compose up --build
```

Two-stage build on `python:3.14.7-alpine`: the builder runs `uv sync --frozen
--no-install-project --no-dev`; the runtime copies `.venv` and `src`, runs as `appuser`, and
starts `uvicorn koffito.asgi:app --proxy-headers` so `ENFORCE_HTTPS` works behind a
TLS-terminating proxy. `compose.yaml` runs the API from `.env`; a commented `jobs` service
shows how to run the job loop separately.

## CI

`.github/workflows/ci.yml` runs on pull requests to `dev` / `main`: `uv sync --frozen`,
`uv lock --check`, ruff, pytest, then builds and pushes the image to GHCR. `push.yml`
notifies the docs repository.

## Conventions

- Async everywhere; one shared `httpx.AsyncClient` per process (created in the lifespan).
- Request bodies extend `schemas.common.StrictModel` (`extra="forbid"`); response models are
  plain `BaseModel`s; identifiers are `UUID`, timestamps `datetime`.
- Services take `(sb, user)` and choose `UserAuth(user.token)`; only `jobs/` uses `ServiceAuth()`.
- Errors: raise `AppError` subclasses in services; PostgREST failures are mapped centrally
  (`supabase/errors.py`). Never log tokens or keys.
- Keep `supabase/migrations/` in sync with the project (see `supabase/README.md`).
- `__init__.py` files re-export public names with a sorted `__all__`; one router per resource.
