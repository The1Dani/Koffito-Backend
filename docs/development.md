# Development

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | `0.12.x` | dependency management, virtualenv, running commands |
| Python | `3.14.7` exactly | pinned in `pyproject.toml` (`requires-python = "==3.14.7"`) |
| Postgres database | 17 | a Supabase project, or a local Postgres container |
| Docker + Compose | any recent | only for the container workflow |

You do not need to install Python yourself — `uv` will fetch 3.14.7 for you.

```bash
# install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Quick start

The app and Alembic both need `DATABASE_URL` pointing at Postgres — there is no
default, and importing the app without it fails with `KeyError: 'DATABASE_URL'`.

```bash
# 1. clone and enter the repo
git clone <repo-url> koffito
cd koffito

# 2. create the virtualenv and install exactly what's in uv.lock
uv sync

# 3. point at the database (see "Database" below)
export DATABASE_URL='postgresql+psycopg://...'

# 4. create the tables
uv run alembic upgrade head

# 5. run the API with autoreload
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

To start over, roll everything back and re-apply:

```bash
uv run alembic downgrade base && uv run alembic upgrade head
```

---

## Database

The database is Postgres on Supabase. Point `DATABASE_URL` at it and both the app and
Alembic follow — `env.py` reads the same value, so they can never disagree.

### Supabase

Copy the connection string from the Supabase dashboard (**Connect** button) and change
the scheme from `postgresql://` to `postgresql+psycopg://`:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres'
```

Use the **direct connection** or the **session pooler** (port `5432`). The transaction
pooler (port `6543`) does not support prepared statements, which psycopg 3 uses
automatically; it would need `connect_args={"prepare_threshold": None}` in
`create_engine`, which is not set.

### Local Postgres

For work that should not touch a shared database, run a throwaway Postgres container:

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

All commands need `DATABASE_URL` set to the database you want to change.

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

Generate against a database that is already at `head` — autogenerate diffs the models
against the live schema, so a stale database produces a migration that re-creates
existing tables.

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
