# Development

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | `0.12.x` | dependency management, virtualenv, running commands |
| Python | `3.14.7` exactly | pinned in `pyproject.toml` (`requires-python = "==3.14.7"`) |
| Docker + Compose | any recent | only for the container workflow |

You do not need to install Python yourself — `uv` will fetch 3.14.7 for you.

```bash
# install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Quick start (SQLite, no database server)

This is the fastest path and needs nothing running in the background. `DATABASE_URL`
defaults to `sqlite:///./koffito.db`, so a local file database is created for you.

```bash
# 1. clone and enter the repo
git clone <repo-url> koffito
cd koffito

# 2. create the virtualenv and install exactly what's in uv.lock
uv sync

# 3. create the tables
uv run alembic upgrade head

# 4. run the API with autoreload
uv run fastapi dev src/koffito/main.py
```

The API is now on <http://127.0.0.1:8000>, with Swagger UI at
<http://127.0.0.1:8000/docs>.

Two equivalent ways to start the server:

```bash
uv run koffito                                  # console script; uvicorn on 127.0.0.1:8000, reload on
uv run uvicorn koffito:app --reload             # the same thing, spelled out
```

Smoke-test it:

```bash
curl http://127.0.0.1:8000/
# {"Hello":"Koffito"}

curl -X POST http://127.0.0.1:8000/venues \
  -H 'content-type: application/json' \
  -d '{"name":"Café Central","address":"Str. Ismail 33","capacity":24}'

curl http://127.0.0.1:8000/venues
```

To start over, delete the database file and re-run the migrations:

```bash
rm -f koffito.db && uv run alembic upgrade head
```

> SQLite is a convenience, not the target. Row-level security is skipped entirely
> (see [database.md](database.md#row-level-security)) and `gen_random_uuid()` does not
> exist there — SQLAlchemy's client-side `uuid4` default covers it. Test anything
> schema-related against Postgres before you trust it.

---

## Running against PostgreSQL

Point `DATABASE_URL` at Postgres and both the app and Alembic follow it — `env.py`
reads the same value, so they can never disagree.

```bash
docker run -d --name koffito-pg \
  -e POSTGRES_USER=koffito -e POSTGRES_PASSWORD=koffito -e POSTGRES_DB=koffito \
  -p 5432:5432 postgres:17.6-trixie

export DATABASE_URL='postgresql+psycopg://koffito:koffito@localhost:5432/koffito'

uv run alembic upgrade head
uv run fastapi dev src/koffito/main.py
```

The URL scheme must be `postgresql+psycopg` (psycopg 3), not the older
`postgresql+psycopg2`.

---

## Docker Compose

`.env` supplies the interpolated values and is **not** committed (`.gitignore` excludes
`.env*`). It needs:

```dotenv
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DB=...
```

Then:

```bash
docker compose up --build
```

Compose defines two services, both built from the repo `Dockerfile`:

- **`db-migrate`** — runs `alembic upgrade head` once and exits.
- **`app`** — waits for `db-migrate` to complete successfully
  (`condition: service_completed_successfully`), then serves uvicorn on port `8000`,
  published to `localhost:8000`.

**Heads up:** the local `db` service in `compose.yaml` is commented out, and both
services point `DATABASE_URL` at the host `staging`:

```
postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@staging:5432/${POSTGRES_DB}
```

Both also set `dns: [100.100.100.100]`, the Tailscale MagicDNS resolver — so `staging`
resolves over the tailnet. As written, `docker compose up` talks to the shared staging
database, not to anything local. To get a self-contained stack, uncomment the `db`
service, the `pg_data_koffito` volume and the `depends_on` blocks, and change `staging`
to `db` in both `DATABASE_URL` values.

Building the image alone:

```bash
docker build -t koffito .
```

The Dockerfile is a two-stage build. The builder runs `uv sync --frozen
--no-install-project --no-dev`, installing third-party dependencies only; the project
itself is never pip-installed, it is put on `PYTHONPATH=/app/src` in the runtime stage.
The runtime image is `python:3.14.7-alpine` running as the non-root user `appuser`.

---

## Migrations

All commands assume `DATABASE_URL` is set the way you want it (unset = SQLite).

```bash
# apply everything
uv run alembic upgrade head

# generate a migration from model changes
uv run alembic revision --autogenerate -m "add events table"

# roll back one revision
uv run alembic downgrade -1

# where am I / what exists
uv run alembic current
uv run alembic history --verbose
```

### Workflow for a schema change

1. Edit or add the model under `src/koffito/models/`.
2. **Export it from `src/koffito/models/__init__.py`** — both the import and `__all__`.
   `alembic/env.py` imports the `models` package for its registration side effect, so a
   model that is not re-exported there is invisible to autogenerate and silently
   produces an empty migration.
3. Run `alembic revision --autogenerate -m "..."`.
4. **Read the generated file.** Autogenerate does not detect everything (enum value
   changes, column renames — it sees a drop plus an add), and the header literally says
   "please adjust".
5. Confirm each new table got an `enable_rls(op, '<table>')` line; `env.py` appends
   these automatically after every `CreateTableOp`.
6. Apply with `alembic upgrade head` and check the downgrade path works too.

Prefer generating against Postgres. Server defaults are rendered per-dialect, and
generating against SQLite produces spellings like `sa.text('(CURRENT_TIMESTAMP)')` —
harmless here, but not what Postgres would have emitted.

---

## Project conventions

- Models use SQLAlchemy 2.0 style: `Mapped[...]` annotations with `mapped_column`.
  Nullability comes from the annotation (`Mapped[str | None]`).
- Enum columns pass `values_callable=lambda e: [m.value for m in e]` so the stored
  value is the lowercase string, not the Python member name. Keep this on new enums.
- UUID primary keys carry both a client-side `default=uuid.uuid4` and a
  `server_default=func.gen_random_uuid()`, so inserts work from either side.
  `profiles` and `admins` are the exception — their ids come from the auth provider.
- One model per module; one router per resource; services raise domain exceptions and
  routes translate them to `HTTPException`. See
  [architecture.md](architecture.md#adding-a-new-resource).
- `__init__.py` files re-export the public names with a sorted `__all__`.

## Not set up yet

There is no test suite, no linter or formatter config, and no pre-commit or CI
configuration in the repo. `pyproject.toml` declares no dev dependency group — the
Dockerfile's `--no-dev` is forward-looking. Adding `pytest` and `ruff` under
`[dependency-groups]` would be the natural next step.
