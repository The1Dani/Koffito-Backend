# Koffito

FastAPI + SQLAlchemy backend for organising social meetup events.

Needs a Postgres database (Supabase) — set `DATABASE_URL` first, see
[docs/development.md](docs/development.md).

```bash
export DATABASE_URL='postgresql+psycopg://...'
uv sync
uv run alembic upgrade head
uv run fastapi dev src/koffito/main.py
```

API on <http://127.0.0.1:8000>, Swagger UI at `/docs`.

## Documentation

- [docs/README.md](docs/README.md) — overview and stack
- [docs/architecture.md](docs/architecture.md) — layering and package layout
- [docs/database.md](docs/database.md) — schema, enums, migrations, RLS
- [docs/api.md](docs/api.md) — endpoints and payloads
- [docs/development.md](docs/development.md) — setup, Docker, migration workflow
