# Database

The schema lives in the Supabase project **koffito** (`gxdebgnkrstzxtlvcsix`) and is owned by
the SQL migrations mirrored in [`supabase/migrations/`](../supabase/README.md). Every table
has row-level security; the backend talks to the database through PostgREST, either **as the
user** (their JWT → role `authenticated`, RLS applies) or **as the service role** (jobs).

## The Data API gate

A PostgREST pre-request hook (`private.check_request`, `pgrst.db_pre_request`) runs before
every Data API call. For the `anon` and `authenticated` roles it requires the header
`X-Koffito-Backend-Key` whose SHA-256 matches `private.backend_settings`; otherwise it raises
`42501 "Koffito data is only available through the Koffito API"`. Only the backend knows the
key (`KOFFITO_BACKEND_KEY`), so the app cannot use `supabase.from()` / `rpc()` at all. The
service role is not gated. Auth endpoints (`/auth/v1/*`) are unaffected.

Rotate with `select private.rotate_backend_key();` (returns the new plaintext once) and update
the backend's environment immediately.

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

## Row-level security (role `authenticated`)

| Table | Policy summary |
| --- | --- |
| `profiles` | select own or admin; update own (column-limited; `is_admin` blocked by trigger) |
| `user_settings` | select / update own |
| `profile_languages` | select own or admin; insert / delete own |
| `surveys` | select own or admin; insert / update own |
| `venues` | select if revealed to me (`can_see_venue`) or admin; admin writes |
| `events` | select non-draft or admin (column grant **excludes** `default_venue_id`); admin writes |
| `groups` | select as member after reveal or admin; admin writes |
| `event_participants` | select own or admin, plus groupmates after reveal |
| `reports` | insert as self; select own or admin; admin update |
| `event_ratings` | insert if attended; select own or admin; update own |

`anon` has no grants at all (it only ever signs in). `service_role` has full access and bypasses RLS.

## SQL functions the backend calls

User-facing (SECURITY DEFINER, keyed on `auth.uid()`; errors are `raise exception '<name>'`):

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
`can_see_venue`, `attended_event`, `profile_card`, `venue_card`. Triggers: `handle_new_user`
(auth.users insert → profile + settings), `protect_is_admin`, `default_reveal_at`,
`inherit_event_venue`, `set_updated_at`.

`rate_event` and `admin_list_events` exist because of the grants: `authenticated` may only
update `(rating, comment)` on `event_ratings` (so a PostgREST upsert cannot work) and may
not read `events.default_venue_id` (blind events).

## Migrations

`supabase/migrations/*.sql` mirror `supabase_migrations.schema_migrations` byte for byte
(checked by md5). See [`supabase/README.md`](../supabase/README.md) for the workflow and for
bootstrapping a fresh project. Alembic is no longer used.

## Advisor notes

Supabase's security advisor flags the SECURITY DEFINER functions as callable by
`authenticated` — intended, they are the API surface and only reachable through the gate —
and the `vector` extension living in `public`. Leaked-password protection is off in Auth
settings and worth enabling in the dashboard.
