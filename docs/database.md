# Database schema

All tables live in the default schema and are created by a single migration,
`alembic/versions/454df7253b33_inital_schema.py` (revision `454df7253b33`, the base
revision — `down_revision` is `None`).

## Entity overview

```
        admins                                 profiles
          │                                    │  │  │  │
  created_by │                    reporter_id ─┘  │  │  └─ user_id ─┐
          ▼                  reported_user_id ────┘  │             │
        events ◄──── event_id ──── reports           │             ▼
          │  ▲                       ▲               │       profile_languages
          │  │                       │               │
          │  └──── event_id ─────────┼───────┐       └─ user_id ──► surveys
          ▼                          │       │
        groups ◄── group_id ── event_participants ── user_id ──► profiles
          │
       venue_id
          ▼
        venues
```

Two identity tables sit at the top: `admins` (staff who create events and reserve
venues) and `profiles` (end users who attend them). Both use the auth provider's user
id as their primary key.

---

## `admins`

Staff accounts. The primary key is **not** generated — it is the same UUID as the auth
user (Supabase `auth.users.id`), so a row is inserted with an id that already exists.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | — | PK, supplied by the caller (auth user id) |
| `display_name` | `String` | yes | — | |
| `avatar_url` | `String` | yes | — | |

## `profiles`

End-user accounts. Same primary-key rule as `admins`.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | — | PK, supplied by the caller (auth user id) |
| `display_name` | `String` | yes | — | |
| `avatar_url` | `String` | yes | — | |
| `date_of_birth` | `Date` | yes | — | |
| `gender` | `gender` enum | yes | — | see [enums](#enums) |

## `profile_languages`

Languages a profile speaks. One row per language, so a profile can have many.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `user_id` | `UUID` | no | — | FK → `profiles.id`, `ON DELETE CASCADE`, indexed |
| `language` | `String` | no | — | free-form string; no enum or lookup table |

**Unique:** `(user_id, language)` — a profile cannot list the same language twice.

## `surveys`

Onboarding / matching questionnaire answers, stored as a JSON blob rather than
normalised columns.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `user_id` | `UUID` | no | — | FK → `profiles.id`, `ON DELETE CASCADE`, indexed |
| `survey_data` | `JSON` | no | — | shape is not constrained by the schema |
| `completed_at` | `Date` | yes | — | null while the survey is still in progress |

Note there is no unique constraint on `user_id`, so a profile may have several surveys.

## `venues`

Places where groups are seated. The only table with an HTTP API today — see
[api.md](api.md).

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | `gen_random_uuid()` | PK; also `uuid4` client-side default |
| `name` | `String` | no | — | |
| `address` | `String` | no | — | |
| `maps_url` | `String` | yes | — | link to the venue on a maps provider |
| `capacity` | `Integer` | no | — | API enforces `> 0`; the DB does not |
| `is_active` | `Boolean` | no | `true` | soft-disable; `GET /venues` returns only active |
| `created_at` | `DateTime(tz)` | no | `now()` | |

## `events`

A scheduled meetup.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | `gen_random_uuid()` | PK |
| `title` | `String` | no | — | |
| `event_at` | `DateTime(tz)` | no | — | when the event happens |
| `capacity` | `Integer` | no | — | total seats across all groups |
| `reveal_at` | `DateTime(tz)` | yes | — | when group assignments become visible |
| `status` | `event_status` enum | no | `draft` | see [enums](#enums) |
| `created_by` | `UUID` | yes | — | FK → `admins.id`, `ON DELETE CASCADE`, indexed |

> `created_by` is nullable but cascades on delete: deleting an admin deletes their
> events rather than orphaning them with a null author.

## `groups`

A subset of an event's participants seated together at one venue.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | `gen_random_uuid()` | PK |
| `event_id` | `UUID` | no | — | FK → `events.id`, `ON DELETE CASCADE`, indexed |
| `venue_id` | `UUID` | no | — | FK → `venues.id`, no cascade, indexed |
| `reserved_by` | `UUID` | yes | — | FK → `admins.id`, `ON DELETE SET NULL` |

`venue_id` has no `ondelete`, so Postgres defaults to `NO ACTION` — a venue with
groups pointing at it cannot be deleted. This is why `venues.is_active` exists.

## `event_participants`

Join table between an event and the profiles attending it, plus the group they were
assigned to and their attendance lifecycle.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | `gen_random_uuid()` | PK |
| `event_id` | `UUID` | no | — | FK → `events.id`, `ON DELETE CASCADE`, indexed |
| `user_id` | `UUID` | no | — | FK → `profiles.id`, `ON DELETE CASCADE`, indexed |
| `group_id` | `UUID` | yes | — | FK → `groups.id`, `ON DELETE SET NULL`, indexed |
| `status` | `participant_status` enum | no | `registered` | see [enums](#enums) |
| `joined_at` | `DateTime(tz)` | no | `now()` | |
| `confirmed_24h_at` | `DateTime(tz)` | yes | — | timestamp of the 24-hour confirmation |
| `confirmed_3h_at` | `DateTime(tz)` | yes | — | timestamp of the 3-hour confirmation |

**Unique:** `(event_id, user_id)` — a profile can register for an event only once.

`group_id` is null until the event's groups are formed, and reverts to null if the
group is deleted, so the participant survives regrouping.

The two `confirmed_*_at` columns implement a two-step attendance check-in: a
participant confirms 24 hours out and again 3 hours out before the event.

## `reports`

Moderation reports raised by one profile against another in the context of an event.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | no | `gen_random_uuid()` | PK |
| `reporter_id` | `UUID` | no | — | FK → `profiles.id`, no cascade, indexed |
| `reported_user_id` | `UUID` | no | — | FK → `profiles.id`, no cascade, indexed |
| `event_id` | `UUID` | no | — | FK → `events.id`, no cascade, indexed |
| `reason` | `String` | no | — | free text |
| `status` | `report_status` enum | no | `open` | see [enums](#enums) |

None of the three foreign keys cascade, so a profile or event that has been reported
cannot be hard-deleted while the report exists — reports are the audit trail.

---

## Enums

Defined in `src/koffito/models/enums.py` as `StrEnum`s and mapped with
`values_callable=lambda e: [m.value for m in e]`, so Postgres stores the **lowercase
value** (`"male"`), not the Python member name (`"MALE"`).

| Type name | Values |
| --- | --- |
| `gender` | `male`, `female`, `non_binary`, `prefer_not_to_say` |
| `event_status` | `draft`, `published`, `revealed`, `completed`, `cancelled` |
| `participant_status` | `registered`, `confirmed`, `cancelled`, `attended`, `no_show` |
| `report_status` | `open`, `reviewing`, `resolved`, `dismissed` |

**Event lifecycle:** `draft` → `published` (registration open) → `revealed` (group
assignments visible, at `reveal_at`) → `completed`. `cancelled` is terminal from
anywhere.

**Participant lifecycle:** `registered` → `confirmed` (after the check-ins) →
`attended` or `no_show`. `cancelled` if they drop out.

---

## Migrations

Alembic is configured in `alembic.ini` with `script_location = %(here)s/alembic` and
`prepend_sys_path = .:%(here)s/alembic` — that second entry is what lets `env.py` and
the generated migrations do a bare `from rls import ...`.

`sqlalchemy.url` is deliberately **not** set in `alembic.ini`. `alembic/env.py`
sets it at runtime from `koffito.db.DATABASE_URL`, so migrations and the app always
agree on the target database. `env.py` also imports `koffito.models` purely for its
side effect of registering every model on `Base.metadata`.

### Row-level security

`alembic/rls.py` defines `enable_rls(op, table_name)`, which issues
`ALTER TABLE "<name>" ENABLE ROW LEVEL SECURITY` — but only when the bound dialect is
`postgresql`, and is a no-op otherwise. The dialect check happens when the migration
*runs*, not when it is generated, so the same migration file is safe against both
SQLite and Postgres.

`process_revision_directives` in `env.py` walks the autogenerated operations and
appends an `EnableRLS` marker after every `CreateTableOp`. The renderer turns that into
a literal `enable_rls(op, 'table_name')` call in the migration file and adds the
import. **Every new table therefore gets RLS enabled automatically** — you do not need
to remember to add it, but you should check it landed in the generated file.

Enabling RLS with no policies attached means the table denies all access to
non-superuser, non-owner roles. Policies are expected to be managed outside these
migrations (in Supabase), which is also why `profiles.id` and `admins.id` mirror
`auth.users.id` — policies can compare against `auth.uid()` directly.

### Caveat: generating migrations against SQLite

Server defaults are rendered from whichever dialect you autogenerate against. The
existing migration was generated against SQLite, which is why it contains
`sa.text('(CURRENT_TIMESTAMP)')` and `sa.text('(true)')` rather than the Postgres
spellings. These are still valid Postgres, but for anything subtler prefer generating
against Postgres and reviewing the diff by hand.

See [development.md](development.md) for the commands.
