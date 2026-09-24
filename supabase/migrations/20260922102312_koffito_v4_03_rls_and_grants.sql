alter table public.profiles enable row level security;
alter table public.user_settings enable row level security;
alter table public.profile_languages enable row level security;
alter table public.surveys enable row level security;
alter table public.venues enable row level security;
alter table public.events enable row level security;
alter table public.groups enable row level security;
alter table public.event_participants enable row level security;
alter table public.reports enable row level security;
alter table public.event_ratings enable row level security;
create policy profiles_select_own_or_admin on public.profiles
for select to authenticated
using (id = auth.uid() or public.is_admin());
create policy profiles_update_own on public.profiles
for update to authenticated
using (id = auth.uid())
with check (id = auth.uid());
create policy settings_select_own on public.user_settings
for select to authenticated
using (user_id = auth.uid());
create policy settings_update_own on public.user_settings
for update to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());
create policy languages_select_own_or_admin on public.profile_languages
for select to authenticated
using (user_id = auth.uid() or public.is_admin());
create policy languages_insert_own on public.profile_languages
for insert to authenticated
with check (user_id = auth.uid());
create policy languages_delete_own on public.profile_languages
for delete to authenticated
using (user_id = auth.uid());
create policy surveys_select_own_or_admin on public.surveys
for select to authenticated
using (user_id = auth.uid() or public.is_admin());
create policy surveys_insert_own on public.surveys
for insert to authenticated
with check (user_id = auth.uid());
create policy surveys_update_own on public.surveys
for update to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());
create policy venues_select_revealed on public.venues
for select to authenticated
using (public.is_admin() or public.can_see_venue(id));
create policy venues_admin_write on public.venues
for all to authenticated
using (public.is_admin())
with check (public.is_admin());
create policy events_select_public on public.events
for select to authenticated
using (status <> 'draft' or public.is_admin());
create policy events_admin_write on public.events
for all to authenticated
using (public.is_admin())
with check (public.is_admin());
create policy groups_select_after_reveal on public.groups
for select to authenticated
using (
public.is_admin()
or (public.is_group_member(id) and public.group_revealed(id))
);
create policy groups_admin_write on public.groups
for all to authenticated
using (public.is_admin())
with check (public.is_admin());
create policy participants_select_own_or_admin on public.event_participants
for select to authenticated
using (user_id = auth.uid() or public.is_admin());
create policy participants_select_groupmates_after_reveal on public.event_participants
for select to authenticated
using (
group_id is not null
and public.is_group_member(group_id)
and public.group_revealed(group_id)
);
create policy reports_insert_self on public.reports
for insert to authenticated
with check (reporter_id = auth.uid());
create policy reports_select_own_or_admin on public.reports
for select to authenticated
using (reporter_id = auth.uid() or public.is_admin());
create policy reports_admin_update on public.reports
for update to authenticated
using (public.is_admin())
with check (public.is_admin());
create policy ratings_select_own_or_admin on public.event_ratings
for select to authenticated
using (user_id = auth.uid() or public.is_admin());
create policy ratings_insert_attended on public.event_ratings
for insert to authenticated
with check (user_id = auth.uid() and public.attended_event(event_id));
create policy ratings_update_own on public.event_ratings
for update to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());
grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
revoke insert, update, delete on public.profiles from authenticated;
grant update (display_name, avatar_emoji, avatar_url, gender, date_of_birth,
occupation, favorite_coffee, onboarded_at)
on public.profiles to authenticated;
revoke insert, update, delete on public.user_settings from authenticated;
grant update (notifications_enabled, reminders_enabled)
on public.user_settings to authenticated;
revoke insert, update, delete on public.surveys from authenticated;
grant insert (user_id, survey_data, completed_at) on public.surveys to authenticated;
grant update (survey_data, completed_at) on public.surveys to authenticated;
revoke select on public.events from authenticated;
grant select (id, title, event_at, capacity, target_group_size, reveal_at,
status, created_by, created_at, updated_at)
on public.events to authenticated;
revoke insert, update, delete on public.event_participants from authenticated;
revoke insert, update, delete on public.reports from authenticated;
grant insert (reporter_id, reported_user_id, event_id, reason, details)
on public.reports to authenticated;
grant update (status, handled_by, reported_user_id) on public.reports to authenticated;
revoke insert, update, delete on public.event_ratings from authenticated;
grant insert (event_id, user_id, rating, comment) on public.event_ratings to authenticated;
grant update (rating, comment) on public.event_ratings to authenticated;
revoke execute on function
public.is_admin(),
public.is_group_member(uuid),
public.group_revealed(uuid),
public.shares_revealed_group(uuid),
public.can_see_venue(uuid),
public.attended_event(uuid),
public.set_my_languages(text[]),
public.join_event(uuid),
public.leave_event(uuid),
public.create_event(timestamptz, int, uuid, boolean, int, text, public.event_status),
public.get_open_events(),
public.get_my_events(),
public.get_public_profile(uuid),
public.get_my_visited_venues(),
public.profile_card(uuid),
public.venue_card(uuid)
from public, anon, authenticated;
grant execute on function
public.is_admin(),
public.is_group_member(uuid),
public.group_revealed(uuid),
public.shares_revealed_group(uuid),
public.can_see_venue(uuid),
public.attended_event(uuid),
public.is_valid_survey_data(jsonb),
public.set_my_languages(text[]),
public.join_event(uuid),
public.leave_event(uuid),
public.create_event(timestamptz, int, uuid, boolean, int, text, public.event_status),
public.get_open_events(),
public.get_my_events(),
public.get_public_profile(uuid),
public.get_my_visited_venues()
to authenticated;
