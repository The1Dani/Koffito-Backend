# Koffito

FastAPI backend for the Koffito coffee-meetup app. The app authenticates with Supabase and
sends every data request here with its Supabase access token; the API verifies the token and
talks to the Supabase database on the user's behalf (so row-level security applies), or with
the service role for background jobs.

```bash
cp .env.example .env        # fill in SUPABASE_PUBLISHABLE_KEY and KOFFITO_BACKEND_KEY
uv sync
uv run koffito              # http://127.0.0.1:8000, Swagger UI at /docs
uv run pytest
```

## Documentation

- [docs/README.md](docs/README.md) — overview and stack
- [docs/frontend-integration.md](docs/frontend-integration.md) — **for the mobile app**: auth flow, API client, every endpoint
- [docs/architecture.md](docs/architecture.md) — request flow, layering, jobs
- [docs/api.md](docs/api.md) — routers, error envelope, rate limits
- [docs/database.md](docs/database.md) — schema, RLS, RPCs, the Data API gate, migrations
- [docs/development.md](docs/development.md) — setup, tests, jobs, Docker, CI
