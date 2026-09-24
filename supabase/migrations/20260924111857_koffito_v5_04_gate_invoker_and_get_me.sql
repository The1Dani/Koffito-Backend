-- The pre-request hook must run as the request role (security invoker) so
-- `current_user` really is anon / authenticated / service_role. The settings
-- table only holds a SHA-256, and schema `private` is never exposed by the API.
grant select on table private.backend_settings to anon, authenticated, service_role;

create or replace function private.check_request()
returns void
language plpgsql
security invoker
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
grant usage on schema extensions to anon, authenticated;
notify pgrst, 'reload config';

-- Everything the app shows about the signed-in user, in one call.
create or replace function public.get_me()
returns jsonb
language sql
stable
security definer
set search_path = 'public'
as $$
select public.get_public_profile(auth.uid())
  || jsonb_build_object(
       'isAdmin', coalesce(p.is_admin, false),
       'onboarded', p.onboarded_at is not null,
       'settings', jsonb_build_object(
         'notificationsEnabled', coalesce(s.notifications_enabled, true),
         'remindersEnabled', coalesce(s.reminders_enabled, true)
       )
     )
from public.profiles p
left join public.user_settings s on s.user_id = p.id
where p.id = auth.uid();
$$;
revoke all on function public.get_me() from public, anon;
grant execute on function public.get_me() to authenticated, service_role;
