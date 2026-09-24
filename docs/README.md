# Koffito — Documentation

Koffito is a coffee-meetup app: people sign up, answer a short survey, join an event, get
matched into a small group, confirm 24 h and 3 h before, and meet at a café that is revealed
shortly before the event. This repository is the **backend API** the mobile app talks to.

## Contents

| Document | What it covers |
| --- | --- |
| [frontend-integration.md](frontend-integration.md) | The contract for the app: Supabase auth setup, API client, every endpoint, error codes |
| [architecture.md](architecture.md) | Request flow, token verification, layering, background jobs |
| [api.md](api.md) | Routers, error envelope, rate limits, OpenAPI |
| [database.md](database.md) | Tables, enums, RLS, SQL functions, the Data API gate, migrations |
| [development.md](development.md) | Local setup, tests, lint, jobs, Docker, CI |

## How the pieces fit

- **Supabase Auth** owns accounts and sessions. The app signs up / in / out and refreshes
  tokens directly with Supabase, and never touches the database through Supabase's Data API
  (a server-side gate rejects such requests).
- **This API** (FastAPI) receives every data request with the user's Supabase access token
  (`Authorization: Bearer …`), verifies it (ES256 signature via the project's JWKS, expiry,
  audience, issuer), and calls Supabase's PostgREST **with that same token** — so the
  database's row-level security decides what each user may see or change. Admin routes
  additionally check `profiles.is_admin` in the database.
- **Background jobs** (24h / 3h reminders; matchmaking and venue assignment as skeletons) run
  in the backend with the service-role key, which bypasses RLS and never leaves the server.

## Stack

- **Python 3.14.7** (pinned exactly), **uv** for dependencies, lockfile and the Docker build
- **FastAPI 0.141** (async), **httpx** (one shared client to Supabase), **pydantic-settings**
- **PyJWT + cryptography** for token verification
- **pytest / pytest-asyncio / ruff** (dev group)
- Supabase project `koffito` (`gxdebgnkrstzxtlvcsix`, Postgres 17, eu-west-1)

## Current state

Complete API surface for the app (`/me`, `/events`, `/users`, `/reports`) and for admins
(`/admin/events`, `/admin/venues`, `/admin/reports`). Reminders are implemented; matchmaking
and venue assignment have their reads and intended writes in place but no algorithm yet.
Push delivery is a logging stub (`LoggingNotifier`).
