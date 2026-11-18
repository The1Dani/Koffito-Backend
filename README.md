# Koffito

FastAPI backend for the Koffito coffee-meetup app. It owns everything: accounts and sign-in
(our own implementation, no third-party auth), the data in our own Postgres, and the rules for
who may see and do what.

```bash
docker compose up -d db mail          # Postgres :5432 + Mailpit (fake inbox) http://localhost:8025
cp .env.example .env                  # set AUTH_JWT_SECRET (see the comment in the file)
uv sync
uv run python -m koffito.migrate      # create / update the schema
uv run python -m koffito.cli seed     # optional: cafés + upcoming coffee talks
uv run koffito                        # http://127.0.0.1:8000, Swagger UI at /docs
uv run pytest                         # needs the db container; creates its own koffito_test DB
```

Make someone an admin: `uv run python -m koffito.cli make-admin you@example.com`.
Background jobs (matchmaking, café assignment, reminders, completion):
`uv run python -m koffito.jobs all --loop`.

The web app ([koffito-web](https://github.com/kynexi/koffito-web)) reaches this API under `/api`
through its dev proxy; run both at the same time.

## Documentation

- [docs/security.md](docs/security.md) — **how authentication and authorization work** (passwords,
  tokens, sessions, email links, rate limits, access rules)
- [docs/frontend-integration.md](docs/frontend-integration.md) — for the app: auth flow, API client,
  every endpoint
- [docs/architecture.md](docs/architecture.md) — request flow, layering, jobs
- [docs/api.md](docs/api.md) — routers, error envelope, rate limits
- [docs/database.md](docs/database.md) — schema, SQL functions, migrations
- [docs/development.md](docs/development.md) — setup, tests, jobs, Docker, CI

The old Supabase migrations stay in `supabase/migrations/` as history only; the live schema is
`db/migrations/`.
