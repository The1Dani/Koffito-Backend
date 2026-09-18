# Koffito — Documentation

Koffito is a FastAPI + SQLAlchemy backend for organising social meetup events: admins
create events at venues, users register, participants get split into groups, and each
group is seated at a venue. Group assignments are hidden until the event's `reveal_at`
moment, which is where the `revealed` event status comes from.

## Contents

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | Layering (routes → services → repositories → models), package layout |
| [database.md](database.md) | Every table, column, enum, constraint and index; migrations and RLS |
| [api.md](api.md) | HTTP endpoints, request/response schemas, status codes |
| [development.md](development.md) | Commands to get running locally, with Docker, and to write migrations |

## Stack

- **Python 3.14.7** (pinned exactly in `pyproject.toml`; `.python-version` says `3.14`)
- **FastAPI 0.141.1** with the `standard` extras (includes `uvicorn`)
- **SQLAlchemy 2.0.52** — declarative ORM with `Mapped[...]` / `mapped_column`
- **Alembic 1.19.2** — schema migrations
- **psycopg 3.3.5** (binary) — PostgreSQL driver
- **uv** — dependency resolution, lockfile (`uv.lock`) and the Docker build

The database is Postgres hosted on Supabase (RLS is enabled per table and
`profiles.id` / `admins.id` mirror `auth.users.id`). `DATABASE_URL` is required — there
is no fallback database.

## Current state

The schema is complete for all nine tables, but only **venues** has an API surface
(routes, schemas, service, repository). Profiles, events, groups, participants, surveys,
reports and admins exist as models and migrations only.
