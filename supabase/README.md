# Supabase

The Koffito database lives in the Supabase project **koffito** (`gxdebgnkrstzxtlvcsix`,
eu-west-1). The cloud project is the source of truth for the schema; the files in
`migrations/` are byte-for-byte mirrors of what has been applied there
(`supabase_migrations.schema_migrations`), kept in this repo so schema changes are reviewed
together with the backend code that depends on them.

## Layout

| File | What it does |
| --- | --- |
| `20260922102219_koffito_v4_01_tables.sql` | tables, enums, triggers, `admin_reports` view |
| `20260922102249_koffito_v4_02_functions.sql` | RLS helper predicates and the user RPCs (`join_event`, `get_me`, …) |
| `20260922102312_koffito_v4_03_rls_and_grants.sql` | RLS policies and column-level grants for `authenticated` |
| `20260922102346_koffito_v4_04_hardening.sql` | `search_path` pinning, `handle_new_user` lockdown |
| `20260924111652_koffito_v5_01_backend_gate.sql` | the Data API gate (`private.check_request` pre-request hook) |
| `20260924111710_koffito_v5_02_client_grants.sql` | `anon` loses every grant; `authenticated` keeps the minimum |
| `20260924111734_koffito_v5_03_participation.sql` | confirmations, attendance, reminder bookkeeping + RPCs |
| `20260924111857_koffito_v5_04_gate_invoker_and_get_me.sql` | gate runs as invoker; `get_me()` |
| `20260924112633_koffito_v5_05_get_my_events_blind.sql` | `get_my_events()` reports blind events |
| `20260924132215_koffito_v6_01_backend_rpcs.sql` | `rate_event()` and `admin_list_events()` for the FastAPI backend |
| `20260924140011_koffito_v6_02_surveys_upsert_grant.sql` | `update (user_id)` on `surveys` so the survey upsert works |

## Making a schema change

1. Write the migration as a new file here (`<YYYYMMDDHHMMSS>_<snake_name>.sql`).
2. Apply it to the project (Supabase MCP `apply_migration`, the SQL editor, or
   `supabase db push` once the CLI is linked) using the **same name**.
3. Confirm the checksum matches what the project recorded:

   ```sql
   select version, name, md5(rtrim(statements[1], E'\n'))
   from supabase_migrations.schema_migrations order by version;
   ```

   ```bash
   python3 -c 'import hashlib,sys; print(hashlib.md5(open(sys.argv[1],"rb").read().rstrip(b"\n")).hexdigest())' supabase/migrations/<file>.sql
   ```
4. Update `docs/database.md` if tables, policies or RPCs changed.

## Bootstrapping a fresh project

Apply the files in order, then arm the Data API gate and give the backend its key:

```sql
select private.rotate_backend_key();  -- copy the result into KOFFITO_BACKEND_KEY
```

Rotating again invalidates the previous key immediately (every user request from a backend
still holding the old key fails with `backend_misconfigured`), so roll the backend right after.

## Security notes

- Every user-facing RPC is `SECURITY DEFINER` and keyed on `auth.uid()`. The Supabase
  advisor flags them as callable by `authenticated`; that is intended — only the backend can
  reach them through the gate, and each one enforces its own rules.
- `authenticated` cannot read `events.default_venue_id` (blind events); admins use
  `admin_list_events()`.
- `service_role` bypasses both RLS and the gate. It is only ever used by background jobs.
