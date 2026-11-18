# Koffito — frontend integration guide

Everything the app needs to talk to Koffito. It describes the *contract*, not the backend's
internals. The web app (`koffito-web`, `src/lib/api.ts`) is the reference implementation.

## 1. The trust model

```
┌──────────────┐   POST /auth/*  (register, verify, login, refresh, logout, …)   ┌──────────────┐
│  App         │ ───────────────────────────────────────────────────────────────▶ │  Koffito API │
│              │ ◀── access token (JSON, 15 min) + refresh token (httpOnly cookie) │  (FastAPI)   │
│              │                                                                   │              │
│              │   every data request: Authorization: Bearer <access_token>       │  verifies,   │
│              │ ───────────────────────────────────────────────────────────────▶ │  then talks  │
│              │ ◀── JSON                                                          │  to Postgres │
└──────────────┘                                                                   └──────────────┘
```

- **One server does everything**: accounts, sessions and data. There is no third-party auth
  SDK in the app and no direct database access.
- The **access token** is short-lived and kept **in memory only** — never in localStorage.
  The **refresh token** is an httpOnly cookie the app's JavaScript never sees.
- The API takes the user id from the token only — **never send your own user id in a
  body**; bodies with unknown fields are rejected with `422`.
- How it is secured is described in [security.md](security.md).

## 2. Environment

The web app calls the API **on its own origin under `/api`**: the Vite dev server proxies
`/api/*` to `http://127.0.0.1:8000/*` (`vite.config.ts`), and in production a reverse proxy does
the same. That keeps the refresh cookie first-party and needs no CORS. If the API must live on
another origin, set `CORS_ORIGINS` on the backend and `AUTH_COOKIE_PATH` to the auth path the
browser uses.

## 3. Auth

All auth routes are under `/auth`. Responses that start a session return
`{"access_token", "token_type": "bearer", "expires_in"}` **and** set the refresh cookie.
Cookie-based routes (`/auth/refresh`, `/auth/logout`) require the header
`X-Requested-With: koffito` (CSRF guard); sending it on every request is simplest.

| Route | Body | Result |
| --- | --- | --- |
| `POST /auth/register` | `{"email", "password", "first_name"}` | `202 {"ok": true}` — always, even if the email is taken. A confirmation link is emailed. |
| `POST /auth/resend-verification` | `{"email"}` | `202` — emails a link to **confirm and choose the password** (`/reset-password?token=…`, handled like a reset) |
| `POST /auth/verify-email` | `{"token"}` (from the link `/verify-email?token=…`) | session; `400 invalid_link` if expired/used |
| `POST /auth/login` | `{"email", "password"}` | session; `401 invalid_credentials`, `403 email_not_verified`, `429 account_locked` |
| `POST /auth/refresh` | — (cookie) | new session; the cookie is rotated. `401 invalid_refresh` → signed out |
| `POST /auth/logout` | — (cookie) | `204`; that sign-in is revoked on every device it reached |
| `POST /auth/forgot-password` | `{"email"}` | `202` — always; a reset link is emailed if the account exists |
| `POST /auth/reset-password` | `{"token", "password"}` (link `/reset-password?token=…`) | `204`; every session is signed out |
| `POST /auth/change-password` | `{"current_password", "new_password"}` + Bearer | new session for this device; others signed out |

Weak passwords are refused with `422 weak_password` and a user-facing message (min 8 chars, not
a common password, not the email). Sign-in attempts are rate limited per IP; email-sending
routes per address.

## 4. Calling the API

One helper does everything: attach the token, and on `401` refresh **once** and retry; if the
refresh is rejected, the session is over. Refreshes must be **serialised across tabs** (the
server revokes a sign-in when a spent refresh token is reused):

```ts
let accessToken: string | null = null;

async function refresh(): Promise<boolean> {
  return navigator.locks.request("koffito-refresh", async () => {
    const r = await fetch("/api/auth/refresh", { method: "POST", headers: { "X-Requested-With": "koffito" } });
    if (!r.ok) return (accessToken = null), false;
    accessToken = (await r.json()).access_token;
    return true;
  });
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const send = () =>
    fetch(`/api${path}`, {
      method: init.method ?? "GET",
      headers: {
        "X-Requested-With": "koffito",
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  let r = await send();
  if (r.status === 401 && (await refresh())) r = await send();
  if (r.status === 204) return undefined as T;
  const data = await r.json();
  if (!r.ok) throw Object.assign(new Error(data.error.message), data.error);
  return data;
}
```

On app start, call `refresh()` once: if it succeeds the user is still signed in (the cookie
lasted), then load `GET /me`.

### Error envelope

Every error has the same shape:

```json
{ "error": { "code": "event_full", "message": "event full", "details": null } }
```

`code` is stable and is what the UI should switch on; `message` is for logs. `details` is
present for `validation_error` (a list of `{loc, msg, type}`) and some constraint errors.

| Status | Codes | Meaning / what to do |
| --- | --- | --- |
| 401 | `missing_token`, `invalid_token`, `token_expired`, `not_authenticated` | Refresh the session once and retry; if it happens again, sign out. Response carries `WWW-Authenticate: Bearer`. |
| 403 | `admin_required`, `forbidden` | Not allowed. Hide the action. |
| 404 | `profile_not_found`, `settings_not_found`, `survey_not_found`, `event_not_found`, `venue_not_found`, `report_not_found`, `not_found` | Nothing there (or not visible to this user). |
| 409 | see the endpoint tables | A business rule said no. Show the specific message. |
| 422 | `validation_error`, `empty_update`, `invalid_stage`, `unknown_language`, `invalid_rating`, `event_in_the_past`, `constraint_violation`, `invalid_reference`, `invalid_value`, `missing_field` | The request is malformed. Fix the form. |
| 429 | `rate_limited` | Back off for `Retry-After` seconds. |
| 5xx | `internal_error`, `backend_misconfigured`, `upstream_error`, `upstream_unavailable`, `upstream_timeout` | Server-side. Retry later, show a generic error. |

### Rate limits

Per user (per API instance): reads 120/min, writes 30/min, reports 5/hour, admin 60/min.
Successful responses with a body carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`
(`204` responses do not).

### Conventions

- All ids are UUIDs. All timestamps are ISO-8601 in UTC (`2026-09-27T06:00:00Z`).
- Request bodies reject unknown fields (`422 validation_error`). Only send what is documented.
- `PATCH` bodies are partial: send only the fields you change. An empty patch is `422 empty_update`.
- Endpoints that act (join, leave, confirm, …) return `204 No Content`.

## 5. Endpoints

`GET /health` — public liveness check, no auth: `{"status":"ok","version":"0.1.0","environment":"production"}`.

### 5.1 Me

#### `GET /me` — profile, stats, admin flag and settings

```json
{
  "id": "66f7bb5d-6b1e-4d7a-8a23-2412e8e3826b",
  "name": "Sergiu",
  "emoji": "☕",
  "gender": "male",
  "age": 30,
  "languages": ["en", "ro"],
  "occupation": "developer",
  "favoriteCoffee": "flat white",
  "survey": { "q1": ["a"] },
  "stats": { "coffeeTalks": 2, "cafesVisited": 1, "peopleMet": 5 },
  "isAdmin": false,
  "onboarded": true,
  "settings": { "notificationsEnabled": true, "remindersEnabled": true }
}
```

`404 profile_not_found` if the account has no profile row (should not happen for accounts
created through sign-up).

#### `PATCH /me` — edit the profile (partial)

Body fields (all optional): `display_name` (1–60 chars, not null), `avatar_emoji` (≤ 8),
`avatar_url` (http(s) URL or null), `gender` (`female|male|non_binary|prefer_not_to_say`),
`date_of_birth` (`YYYY-MM-DD`, must be 18+), `occupation` (≤ 80), `favorite_coffee` (≤ 80),
`onboarded` (`true` marks onboarding complete, `false` clears it).

Response — the profile row (snake_case):

```json
{
  "id": "…", "display_name": "Sergiu", "avatar_emoji": "☕", "avatar_url": null,
  "gender": "male", "date_of_birth": "1995-01-01", "occupation": "developer",
  "favorite_coffee": "flat white", "onboarded_at": "2026-09-22T12:50:25Z",
  "created_at": "2026-09-22T12:44:10Z", "updated_at": "2026-09-24T10:00:00Z"
}
```

`is_admin` is read-only and cannot be sent.

#### `PUT /me/languages` — replace the language list

Body `{"languages": ["ro", "en"]}` (values `ro|ru|en`, unique, max 3). Response `{"languages": ["en", "ro"]}`.

#### `PATCH /me/settings`

Body (partial) `{"notifications_enabled": true, "reminders_enabled": false}`.
Response `{"notifications_enabled": true, "reminders_enabled": false, "updated_at": "…"}`.

#### `GET /me/survey`

```json
{ "survey_data": { "q1": ["a", "b"], "q2": ["c"] }, "completed_at": "2026-09-22T12:50:25Z", "completed": true }
```

`404 survey_not_found` until the user saves one.

#### `PUT /me/survey` — create or replace the survey

Body `{"survey_data": {"<questionId>": ["<answer>", …]}, "completed": true}`. Every value
must be an array of strings (a draft can be saved with `"completed": false`). Users cannot
join events until a survey is **completed**. Response: same shape as `GET /me/survey`.

#### `GET /me/events` — the user's coffee talks (past and upcoming)

```json
[
  {
    "id": "cee809b6-ac52-4a29-9264-63083df8f479",
    "event_at": "2026-09-27T06:00:00Z",
    "reveal_at": "2026-09-26T06:00:00Z",
    "status": "pending",
    "participant_status": "joined",
    "joined": true,
    "blind": true,
    "location_hidden": true,
    "reveal_opened": false,
    "max_participants": 4,
    "cafe": null,
    "participants": null,
    "attended": null,
    "attendance_note": null,
    "my_rating": null,
    "my_comment": null
  }
]
```

- `status`: `pending` (joined/matched, not confirmed) · `confirmed` · `completed` · `cancelled`.
- `participant_status`: the raw state `joined|matched|confirmed_24h|confirmed_3h|declined|cancelled|no_show`.
- `blind`: the café is hidden until `reveal_at`. `location_hidden`: it is *still* hidden now.
- Once revealed, `cafe` is a venue card (see `GET /me/venues`) and `participants` is a list of
  groupmate cards: `{id, name, emoji, gender, age, languages, occupation, favoriteCoffee, survey}`.
- `reveal_opened`: the user already opened the reveal (`POST /events/{id}/reveal`).

#### `GET /me/venues` — cafés the user has visited (most recent first)

```json
[
  { "id": "…", "name": "Tucano Coffee", "description": "", "photo": null, "address": "Str. Ismail 33",
    "website": null, "phone": null, "mapsUrl": null, "rating": 4.5, "popularTimes": [10, 20, 30, 40, 50, 60, 70] }
]
```

### 5.2 Events

#### `GET /events` — open events the user can join

```json
[
  { "id": "…", "event_at": "2026-09-27T06:00:00Z", "max_participants": 4, "spots_left": 39, "joined": false }
]
```

`max_participants` is the group size; `spots_left` counts the whole event.

#### `POST /events/{id}/join` → `204`

409 codes: `survey_incomplete` (finish the survey first), `event_not_open`, `time_conflict`
(another event within ±2 h), `event_full`. Re-joining after leaving is allowed.

#### `POST /events/{id}/leave` → `204`

409 `nothing_to_cancel` (not a participant, or the event already started).

#### `POST /events/{id}/confirm` → `204`

Body `{"stage": "24h"}` or `{"stage": "3h"}`. The server sends reminders at those points;
the user confirms attendance from the app. 409 `event_not_confirmable` (event over,
cancelled or draft), `nothing_to_confirm` (already confirmed, or not a participant);
422 `invalid_stage`.

#### `POST /events/{id}/reveal` → `204`

Call when the user opens the revealed café card, so it stays open. 409 `not_revealed_yet`.

#### `POST /events/{id}/attendance` → `204`

After the event: `{"happened": true}` or `{"happened": false, "note": "nobody showed up"}`
(`note` ≤ 500 chars, optional). 409 `nothing_to_confirm` (event not over yet / not a participant).

#### `PUT /events/{id}/rating` — rate an attended event

Body `{"rating": 5, "comment": "great people"}` (`rating` 1–5, `comment` ≤ 1000, optional).
Creates or replaces the rating. Response:

```json
{ "event_id": "…", "rating": 5, "comment": "great people", "created_at": "…", "updated_at": "…" }
```

409 `not_attended` (the event has not happened yet, or the user was not there).

### 5.3 Users

#### `GET /users/{id}` — a groupmate's card

Visible for people the user shares a *revealed* group with (and for admins). Otherwise
`404 profile_not_found` — the API does not distinguish "hidden" from "missing".

```json
{
  "id": "…", "name": "Gabi", "emoji": "🍵", "gender": "female", "age": 28, "languages": ["ro"],
  "occupation": null, "favoriteCoffee": "latte", "survey": {},
  "stats": { "coffeeTalks": 1, "cafesVisited": 1, "peopleMet": 3 }
}
```

### 5.4 Reports

#### `POST /reports` → `201`

```json
{ "reported_user_id": "…", "event_id": "…", "reason": "rude", "details": "was rude to everyone at the table" }
```

`reason`: `no-show|rude|unsafe|fake|other`. `details`: 10–2000 chars. `reported_user_id` and
`event_id` are optional. The reporter is always the signed-in user. Limited to 5 per hour.

Response:

```json
{ "id": "…", "reason": "rude", "details": "…", "status": "open", "event_id": "…", "reported_user_id": "…", "created_at": "…" }
```

### 5.5 Admin (only when `GET /me` says `isAdmin: true`)

Admin-ness is decided by the server on every request (`profiles.is_admin`); a non-admin gets
`403 admin_required`. Do not cache the flag beyond the current session.

| Method & path | Body / query | Response |
| --- | --- | --- |
| `GET /admin/events?status=&from=&to=&limit=50&offset=0` | filters optional (`status` is an event status, `from`/`to` ISO datetimes) | `{"items": [Event], "total", "limit", "offset"}` |
| `POST /admin/events` → 201 | `{"event_at": "<future ISO>", "target_group_size": 4, "default_venue_id": null, "location_hidden": true, "capacity": 40, "title": null, "status": "open"}` (only `event_at` required) | `Event` |
| `GET /admin/events/{id}` | | `Event` (404 `event_not_found`) |
| `PATCH /admin/events/{id}` | partial: `title`, `event_at`, `reveal_at` (≤ event_at), `capacity`, `target_group_size` (2–8), `default_venue_id`, `status` (`draft|open|matched|confirmed|completed|cancelled`) | `Event` |
| `GET /admin/events/{id}/participants` | | `[{"id", "user_id", "status", "group_id", "joined_at", "confirmed_24h_at", "confirmed_3h_at", "cancelled_at", "attended", "attendance_note", "reveal_opened_at", "reminded_24h_at", "reminded_3h_at", "profile": {"display_name", "avatar_emoji"}}]` |
| `GET /admin/venues?include_inactive=false` | | `[Venue]` |
| `POST /admin/venues` → 201 | `{"name", "address", "description", "photo_url", "website", "phone", "maps_url", "google_place_id", "latitude", "longitude", "rating" (0–5), "popular_times" (7 ints), "capacity" (>0), "is_active"}` (`name`, `address` required) | `Venue` |
| `GET /admin/venues/{id}` · `PATCH /admin/venues/{id}` | partial body | `Venue` (404 `venue_not_found`) |
| `DELETE /admin/venues/{id}` → 204 | soft delete: `is_active=false` | |
| `GET /admin/reports?status=&limit=50&offset=0` | `status`: `open|reviewing|resolved` | `{"items": [Report], "total", "limit", "offset"}` |
| `PATCH /admin/reports/{id}` | `{"status": "reviewing"}` | `{"id", "status", "handled_by", "updated_at"}` (`handled_by` = the admin) |

`Event`:

```json
{ "id": "…", "title": null, "event_at": "…", "capacity": 40, "target_group_size": 4, "reveal_at": "…",
  "default_venue_id": "…", "status": "open", "created_by": "…", "created_at": "…", "updated_at": "…" }
```

`Venue`: all columns (`id, name, description, photo_url, address, website, phone, maps_url,
google_place_id, latitude, longitude, rating, popular_times, capacity, is_active, created_at`).

`Report` (admin view): `id, reason, details, status, created_at, updated_at, event_id, reporter_id,
reported_by (name), reported_user_id, reported_user_name, handled_by`.

## 6. Typical flows

**Onboarding**: sign up → confirm email → sign in → `GET /me` (`onboarded: false`) →
`PATCH /me` (name, birth date, …) → `PUT /me/languages` → `PUT /me/survey` →
`PATCH /me {"onboarded": true}`.

**Joining**: `GET /events` → `POST /events/{id}/join` → the event shows up in `GET /me/events`
as `pending`. The server matches groups and picks the café; at `reveal_at` the item gains
`cafe` + `participants` and `location_hidden` turns false.

**Before the meetup**: the server sends a 24h and a 3h reminder (push, once wired up; the
app should also nudge from `GET /me/events` timings) → `POST /events/{id}/confirm`
with the matching `stage`.

**After**: `POST /events/{id}/attendance` → `PUT /events/{id}/rating` → `POST /reports` if
something went wrong. Groupmates stay visible via `GET /users/{id}`.

## 7. Things the app must NOT do

- Store the access token in `localStorage` / `sessionStorage` — keep it in memory.
- Refresh from two tabs at once — serialise with `navigator.locks` (a reused refresh token
  ends the session).
- Put user ids (`user_id`, `reporter_id`, …) in request bodies — they are rejected.
- Call the API over plain `http://` in production.
- Treat a token claim as proof of admin rights — only `GET /me` → `isAdmin` (server-checked
  again on every admin call) counts.

## 8. OpenAPI

The running API serves Swagger UI at `/docs`, ReDoc at `/redoc` and the schema at
`/openapi.json` — the request/response models above are generated from the same code.
