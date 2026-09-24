-- Koffito v5: Data API grants for clients.
-- * `anon` never needs the database (auth only), so it loses every grant.
-- * `authenticated` keeps the minimum the backend needs when it acts on the
--   user's behalf with the user's own token; RLS decides which rows.

revoke all privileges on all tables in schema public from anon;
revoke all privileges on all sequences in schema public from anon;
revoke all privileges on all functions in schema public from anon;
alter default privileges for role postgres in schema public revoke all on tables from anon;
alter default privileges for role postgres in schema public revoke all on sequences from anon;
alter default privileges for role postgres in schema public revoke all on functions from anon;

-- The reports view used to run with its owner's privileges, which let any
-- signed-in user read every report. Make it respect RLS on `reports`.
alter view public.admin_reports set (security_invoker = true);
revoke all on public.admin_reports from anon, authenticated;
grant select on public.admin_reports to authenticated;

-- Column-level writes for the signed-in user (row access is still RLS).
grant update (display_name, avatar_emoji, avatar_url, gender, date_of_birth,
              occupation, favorite_coffee, onboarded_at)
  on public.profiles to authenticated;

grant insert (user_id, survey_data, completed_at),
      update (survey_data, completed_at)
  on public.surveys to authenticated;

grant update (notifications_enabled, reminders_enabled)
  on public.user_settings to authenticated;

grant insert (reporter_id, reported_user_id, event_id, reason, details),
      update (status, handled_by)
  on public.reports to authenticated;

grant insert (event_id, user_id, rating, comment),
      update (rating, comment)
  on public.event_ratings to authenticated;

-- Nobody should be able to TRUNCATE through the API.
revoke truncate on all tables in schema public from authenticated;
