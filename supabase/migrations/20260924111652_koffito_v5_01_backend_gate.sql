-- Koffito v5: the app never talks to the Data API directly. Every request from
-- an `anon` / `authenticated` role must carry the backend's shared key in the
-- `X-Koffito-Backend-Key` header, which only the FastAPI server knows. The
-- service role (backend system jobs) is not gated.

create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to anon, authenticated, service_role;

create table if not exists private.backend_settings (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);
revoke all on table private.backend_settings from public, anon, authenticated, service_role;

-- Generates a fresh backend key, stores only its SHA-256 and returns the
-- plaintext once. Run `select private.rotate_backend_key();` from the SQL
-- editor and put the result in the backend's KOFFITO_BACKEND_KEY.
create or replace function private.rotate_backend_key()
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_key text := encode(extensions.gen_random_bytes(32), 'hex');
begin
  insert into private.backend_settings (key, value)
  values ('backend_key_sha256', encode(extensions.digest(v_key, 'sha256'), 'hex'))
  on conflict (key) do update
    set value = excluded.value, updated_at = now();
  return v_key;
end;
$$;
revoke all on function private.rotate_backend_key() from public, anon, authenticated, service_role;

-- PostgREST pre-request hook: runs as the request role before every Data API call.
create or replace function private.check_request()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_header text;
  v_expected text;
begin
  if current_user not in ('anon', 'authenticated') then
    return;
  end if;

  v_header := coalesce(current_setting('request.headers', true), '{}')::jsonb ->> 'x-koffito-backend-key';
  select value into v_expected
  from private.backend_settings
  where key = 'backend_key_sha256';

  if v_expected is null
     or v_header is null
     or encode(extensions.digest(v_header, 'sha256'), 'hex') <> v_expected then
    raise exception 'Koffito data is only available through the Koffito API'
      using errcode = '42501',
            hint = 'Direct Data API access is disabled for app clients.';
  end if;
end;
$$;
revoke all on function private.check_request() from public;
grant execute on function private.check_request() to anon, authenticated, service_role;

alter role authenticator set pgrst.db_pre_request = 'private.check_request';
notify pgrst, 'reload config';
