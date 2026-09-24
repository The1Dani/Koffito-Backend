# HTTP API

The endpoint reference the mobile app is built against lives in
[frontend-integration.md](frontend-integration.md) — request bodies, response JSON and
error codes for every route. This page is the short map.

Base URL in local development: `http://127.0.0.1:8000`. Swagger UI at `/docs`, ReDoc at
`/redoc`, schema at `/openapi.json`.

## Authentication

Every route except `GET /health` requires `Authorization: Bearer <Supabase access token>`.
`401` responses carry `WWW-Authenticate: Bearer error="invalid_token"` and one of
`missing_token`, `invalid_token`, `token_expired`, `unknown_kid`. Admin routes return
`403 admin_required` unless `profiles.is_admin` is true for the caller.

## Routers

| Router | Prefix | Rate limit | Source |
| --- | --- | --- | --- |
| health | `/health`, `/` | none | `api/routes/root.py` |
| me | `/me` | read 120/min, write 30/min | `api/routes/me.py` |
| events | `/events` | read 120/min, write 30/min | `api/routes/events.py` |
| users | `/users` | read 120/min | `api/routes/users.py` |
| reports | `/reports` | 5/hour | `api/routes/reports.py` |
| admin | `/admin/events`, `/admin/venues`, `/admin/reports` | 60/min | `api/routes/admin_*.py` |

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | liveness |
| GET / PATCH | `/me` | profile + stats + settings / edit profile |
| PUT | `/me/languages` | replace languages |
| PATCH | `/me/settings` | notification / reminder toggles |
| GET / PUT | `/me/survey` | read / save the survey |
| GET | `/me/events` | my coffee talks |
| GET | `/me/venues` | cafés I visited |
| GET | `/events` | open events |
| POST | `/events/{id}/join` · `/leave` · `/confirm` · `/reveal` · `/attendance` | participation actions (204) |
| PUT | `/events/{id}/rating` | rate an attended event |
| GET | `/users/{id}` | groupmate card (after reveal) |
| POST | `/reports` | file a report |
| GET / POST | `/admin/events` | list / create events |
| GET / PATCH | `/admin/events/{id}` | read / edit an event |
| GET | `/admin/events/{id}/participants` | participants with profile |
| GET / POST | `/admin/venues` | list / create venues |
| GET / PATCH / DELETE | `/admin/venues/{id}` | read / edit / deactivate |
| GET | `/admin/reports` | triage list |
| PATCH | `/admin/reports/{id}` | set status (handled_by = admin) |

## Error envelope

```json
{ "error": { "code": "event_full", "message": "event full", "details": null } }
```

`code` is stable. `422 validation_error` carries `details: [{loc, msg, type}]`. `429` carries
`Retry-After`. Successful responses carry `X-RateLimit-Limit` / `X-RateLimit-Remaining`.
The full code table is in [frontend-integration.md](frontend-integration.md#error-envelope).
