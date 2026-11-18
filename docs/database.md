# Database

Our own Postgres 17 (with `pgvector`), run locally by `docker compose up -d db`. The schema is
owned by [`db/migrations/`](../db/migrations) and applied with `python -m koffito.migrate`.

The FastAPI backend is the **only** client. Per request it opens a transaction and sets
`app.user_id` (transaction-local); SQL functions read it through `app.uid()`. Background jobs
and the auth service run without a user (`app.uid()` is null). See [security.md](security.md).

## Accounts (our auth)

| Table | Purpose |
| --- | --- |
| `users` | `email` (citext, unique), `password_hash` (Argon2id), `email_verified_at`, `failed_logins`, `locked_until`, `password_changed_at` |
| `refresh_tokens` | SHA-256 of each refresh token, `family_id` (one per sign-in), `expires_at`, `revoked_at`, `replaced_by` (rotation chain) |
| `email_tokens` | SHA-256 of verify / reset link tokens, `purpose`, `expires_at`, `used_at` |

A `profiles` row (and `user_settings`) is created in the same statement as the `users` row.

## Tables (schema `public`)

| Table | Purpose | Key columns |
| --- | --- | --- |
| `profiles` | one per auth user (`id` = `auth.users.id`, created by trigger) | `display_name`, `avatar_emoji`, `avatar_url`, `gender`, `date_of_birth` (18+), `occupation`, `favorite_coffee`, `onboarded_at`, `is_admin` (read-only through the API) |
| `user_settings` | per user (created by trigger) | `notifications_enabled`, `reminders_enabled` |
| `profile_languages` | languages per user | `language` ∈ `ro, ru, en`, unique per user |
| `surveys` | one per user | `survey_data` jsonb `{question: [answers]}`, `embedding vector(64)`, `embedding_version`, `completed_at` |
| `venues` | cafés | `name`, `address`, `description`, `photo_url`, `website`, `phone`, `maps_url`, `google_place_id`, `latitude`, `longitude`, `rating` 0–5, `popular_times` int[7], `capacity`, `is_active` |
| `events` | a coffee talk | `title`, `event_at`, `capacity` (default 40), `target_group_size` 2–8, `reveal_at` ≤ `event_at` (default `event_at − 24h`), `default_venue_id`, `status`, `created_by` |
| `groups` | a matched group | `event_id`, `venue_id` (inherited from the event on insert), `reserved_by`, `reservation_status`, `reservation_notes`, `avg_distance` |
| `event_participants` | user ↔ event (unique) | `group_id`, `status`, `joined_at`, `confirmed_24h_at`, `confirmed_3h_at`, `cancelled_at`, `attended`, `attendance_note`, `reveal_opened_at`, `reminded_24h_at`, `reminded_3h_at` |
| `reports` | moderation | `reporter_id`, `reported_user_id`, `event_id`, `reason`, `details` (≥ 10 chars), `status`, `handled_by` |
| `event_ratings` | user ↔ event rating (unique) | `rating` 1–5, `comment` |
| `admin_reports` (view, security invoker) | reports joined with reporter / reported names | |

All tables carry `created_at` and, where they change, `updated_at` (trigger).

## Enums

| Type | Values |
| --- | --- |
| `gender` | `female`, `male`, `non_binary`, `prefer_not_to_say` |
| `event_status` | `draft`, `open`, `matched`, `confirmed`, `completed`, `cancelled` |
| `participant_status` | `joined`, `matched`, `confirmed_24h`, `confirmed_3h`, `declined`, `cancelled`, `no_show` |
| `reservation_status` | `pending`, `confirmed`, `cancelled` |
| `report_status` | `open`, `reviewing`, `resolved` |
| `report_reason` | `no-show`, `rude`, `unsafe`, `fake`, `other` |

Event lifecycle: `draft` → `open` (joinable) → `matched` (groups formed) → `confirmed`
(reservations done) → `completed`; `cancelled` from anywhere. Participant lifecycle:
`joined` → `matched` → `confirmed_24h` → `confirmed_3h`; `cancelled` if they leave,
`no_show` from their own attendance answer.

## Access rules

There is no row-level security: the database is not exposed to clients. The rules that used to
be RLS policies are enforced by the SQL functions (keyed on `app.uid()`) and by the repositories,
which always filter on the user id from the access token. Admin data is only read behind
`require_admin`. `tests/test_access_rules.py` checks every rule against a real database.

## SQL functions the backend calls

User-facing (keyed on `app.uid()`; errors are `raise exception '<name>'`):

| Function | Used by | Raises |
| --- | --- | --- |
| `get_me()` | `GET /me` | |
| `get_public_profile(p_user_id)` | `GET /users/{id}` | (returns null when not visible) |
| `set_my_languages(p_languages)` | `PUT /me/languages` | `unknown_language` |
| `get_my_events()` / `get_my_visited_venues()` | `GET /me/events`, `GET /me/venues` | |
| `get_open_events()` | `GET /events` | |
| `join_event(p_event_id)` | `POST /events/{id}/join` | `survey_incomplete`, `event_not_open`, `time_conflict`, `event_full` |
| `leave_event(p_event_id)` | `…/leave` | `nothing_to_cancel` |
| `confirm_event(p_event_id, p_stage)` | `…/confirm` | `invalid_stage`, `event_not_confirmable`, `nothing_to_confirm` |
| `open_reveal(p_event_id)` | `…/reveal` | `not_revealed_yet` |
| `report_attendance(p_event_id, p_happened, p_note)` | `…/attendance` | `nothing_to_confirm` |
| `rate_event(p_event_id, p_rating, p_comment)` | `PUT /events/{id}/rating` | `invalid_rating`, `not_attended` |
| `is_admin()` | every admin route | |
| `create_event(...)` | `POST /admin/events` | `not_admin`, `event_in_the_past` |
| `admin_list_events()` | `GET /admin/events[/{id}]` | (empty for non-admins) |

Helpers used by policies: `is_group_member`, `group_revealed`, `shares_revealed_group`,
`can_see_venue`, `attended_event`, `profile_card`, `venue_card`. Triggers: `default_reveal_at`,
`inherit_event_venue`, `set_updated_at`.

`rate_event` upserts the caller's rating only if they attended; `admin_list_events` returns
rows only for admins (it is the one place `events.default_venue_id` is read for blind events).

## Migrations

`db/migrations/NNN_name.sql`, applied in order by `python -m koffito.migrate` and recorded with
their SHA-256 in `schema_migrations`. A migration that changed after it was applied is an
error: add a new file instead of editing an old one. `supabase/migrations/` is the old history
and is not applied any more.
