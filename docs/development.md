# Development

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | dependencies, virtualenv, running commands (downloads Python for you) |
| Python | 3.14.7 exactly | `requires-python = "==3.14.7"` |
| Docker + Compose | any recent | Postgres and Mailpit (and optionally the API itself) |

## Configuration

Copy `.env.example` to `.env` and fill it in. `.env` is git-ignored; every value can also be
a real environment variable.

| Variable | Required | Meaning |
| --- | --- | --- |
| `AUTH_JWT_SECRET` | yes | HMAC key for access tokens, ≥ 32 random characters |
| `DATABASE_URL` | no | defaults to the compose database `postgresql://koffito:koffito@localhost:5432/koffito` |
| `APP_BASE_URL` | no | where email links point (the web app), default `http://localhost:5173` |
| `SMTP_*`, `MAIL_FROM` | no | defaults to Mailpit on `localhost:1025` |
| `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS`, `*_TTL_*`, `LOGIN_*` | no | session and lockout tuning |
| `AUTH_COOKIE_PATH` | no | path the browser uses for `/auth` (default `/api/auth`, behind the web app's proxy) |
| `JOBS_ENABLED`, `JOBS_INTERVAL_SECONDS` | no | run the job loop inside this process (one instance only) |
| `RATE_LIMIT_*` | no | limits; `RATE_LIMIT_ENABLED=false` switches them off |
| `ENVIRONMENT`, `ENFORCE_HTTPS`, `TRUSTED_HOSTS`, `CORS_ORIGINS`, `LOG_LEVEL` | no | deployment; production requires `ENFORCE_HTTPS=true` and explicit `TRUSTED_HOSTS` |

The settings model is `src/koffito/core/config.py`.

## Run

```bash
docker compose up -d db mail              # Postgres :5432, Mailpit SMTP :1025 / inbox :8025
uv sync
uv run python -m koffito.migrate          # apply db/migrations
uv run python -m koffito.cli seed         # optional demo cafés + coffee talks
uv run koffito                            # uvicorn with reload on 127.0.0.1:8000
```

Swagger UI: <http://127.0.0.1:8000/docs>. Every email the API sends shows up in Mailpit at
<http://localhost:8025> (confirmation and reset links included).

Admin rights: `uv run python -m koffito.cli make-admin you@example.com` (or `revoke-admin`).

Manual token for curl:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"…"}' | jq -r .access_token)
curl -s localhost:8000/me -H "authorization: Bearer $TOKEN" | jq
```

On Windows the async Postgres driver needs a selector event loop; `uv run koffito`, the jobs
CLI and the tests already set it up.

## Tests and lint

```bash
uv run pytest                              # needs `docker compose up -d db`
uv run ruff check . && uv run ruff format --check .
```

The test suite creates a throwaway `koffito_test` database from `db/migrations` once per run
and empties every table before each test. Emails are captured in memory (`Outbox` in
`tests/conftest.py`). Point `TEST_DATABASE_URL` / `TEST_ADMIN_DATABASE_URL` elsewhere if
needed; without a reachable Postgres the database tests are skipped.

## Background jobs

```bash
uv run python -m koffito.jobs matchmaking        # one shot: matchmaking | venues | reminders | completion
uv run python -m koffito.jobs all --loop         # every JOBS_INTERVAL_SECONDS
```

In-process (`JOBS_ENABLED=true`) is the single-instance convenience; with several replicas run
the CLI from one cron or one container instead (`docker compose --profile full up` starts it as
the `jobs` service).

## Docker

```bash
docker compose --profile full up --build   # db + mail + API (migrates on start) + jobs
```

Two-stage build on `python:3.14.7-alpine`: the builder runs `uv sync --frozen
--no-install-project --no-dev`; the runtime copies `.venv` and `src`, runs as `appuser`, and
starts uvicorn with `--proxy-headers` so `ENFORCE_HTTPS` works behind a TLS-terminating proxy.

## CI

`.github/workflows/ci.yml` runs on pull requests to `dev` / `main` with a Postgres service:
`uv sync --frozen`, `uv lock --check`, ruff, pytest, then builds and pushes the image to GHCR.
`push.yml` notifies the docs repository.

## Conventions

- Async everywhere; one shared database pool per process (created in the lifespan).
- Request bodies extend `schemas.common.StrictModel` (`extra="forbid"`); response models are
  plain `BaseModel`s; identifiers are `UUID`, timestamps `datetime`.
- Services take `(db, user)` and use `UserAuth(user.id)`; only `jobs/` and `auth/` use
  `ServiceAuth()`.
- SQL: values are always parameters; identifiers go through `db.database._ident`. Schema
  changes are new files in `db/migrations/`, never edits to applied ones.
- Errors: raise `AppError` subclasses in services; database failures are mapped centrally
  (`db/errors.py`). Never log tokens, passwords or keys.
- `__init__.py` files re-export public names with a sorted `__all__`; one router per resource.
