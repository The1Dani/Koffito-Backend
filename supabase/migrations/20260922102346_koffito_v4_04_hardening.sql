alter function public.set_updated_at() set search_path = public;
alter function public.protect_is_admin() set search_path = public;
alter function public.default_reveal_at() set search_path = public;
alter function public.inherit_event_venue() set search_path = public;
alter function public.is_valid_survey_data(jsonb) set search_path = public;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
