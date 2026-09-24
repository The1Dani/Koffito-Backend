-- Koffito v6.02: PUT /me/survey is a PostgREST upsert (INSERT ... ON CONFLICT (user_id) DO
-- UPDATE), and Postgres requires UPDATE privilege on every column the upsert sets — including
-- user_id. RLS (`surveys_update_own`: with check user_id = auth.uid()) still pins the row to its
-- owner. The live project already carried this grant applied by hand; recording it here makes
-- environments built from these migrations behave the same.
grant update (user_id) on public.surveys to authenticated;
