# Koffito — Documentation

Koffito is a coffee-meetup app: people sign up, answer a short survey, join an event, get
matched into a small group, confirm 24 h and 3 h before, and meet at a café that is revealed
shortly before the event. This repository is the **backend API** the app talks to.

## Contents

| Document | What it covers |
| --- | --- |
| [security.md](security.md) | Our own authentication and authorization: passwords, tokens, sessions, email links, rate limits, access rules |
| [frontend-integration.md](frontend-integration.md) | The contract for the app: auth routes, API client, every endpoint, error codes |
| [architecture.md](architecture.md) | Request flow, layering, background jobs |
| [api.md](api.md) | Routers, error envelope, rate limits, OpenAPI |
| [database.md](database.md) | Tables, enums, SQL functions, access rules, migrations |
| [development.md](development.md) | Local setup, tests, lint, jobs, Docker, CI |

## How the pieces fit

- **This API owns accounts and sessions.** Sign-up with email confirmation, sign-in,
  rotating refresh tokens in an httpOnly cookie, short-lived access tokens, password
  reset/change — all implemented here (`src/koffito/auth`).
- **Every data request** carries `Authorization: Bearer <access token>`. The API verifies it,
  then works in **our own Postgres** inside a transaction that knows the user
  (`app.user_id`); the SQL functions decide what each user may see or change. Admin routes
  additionally check `profiles.is_admin`.
- **Background jobs** (matchmaking, venue assignment, 24 h / 3 h reminders, event completion)
  run in the backend without a user.
- **Email** goes out over SMTP; locally Mailpit catches it (http://localhost:8025).

## Stack

- **Python 3.14.7** (pinned exactly), **uv** for dependencies, lockfile and the Docker build
- **FastAPI 0.141** (async), **pydantic-settings**
- **Postgres 17 + pgvector** via **psycopg 3** (async pool)
- **argon2-cffi** (passwords), **PyJWT** (access tokens), **aiosmtplib** (email)
- **pytest / pytest-asyncio / ruff** (dev group); tests run against a real Postgres

## Current state

Complete API surface for the app (`/auth`, `/me`, `/events`, `/users`, `/reports`) and for
admins (`/admin/events`, `/admin/venues`, `/admin/reports`). All four jobs run: reminders, a v1
matchmaking (groups in join order), a v1 venue assignment (largest active café that seats the
group) and event completion (2 h after the start). Reminders go out by email
(`EmailNotifier`, times in `APP_TIMEZONE`); similarity-based matching is the intended v2.
