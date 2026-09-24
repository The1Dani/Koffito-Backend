create or replace function public.is_group_member(gid uuid)
returns boolean
language sql security definer stable set search_path = public
as $$
select exists (
select 1 from public.event_participants
where group_id = gid
and user_id = auth.uid()
and status not in ('cancelled', 'declined')
);
$$;
create or replace function public.group_revealed(gid uuid)
returns boolean
language sql security definer stable set search_path = public
as $$
select exists (
select 1
from public.groups g
join public.events e on e.id = g.event_id
where g.id = gid and e.reveal_at <= now()
);
$$;
create or replace function public.shares_revealed_group(other uuid)
returns boolean
language sql security definer stable set search_path = public
as $$
select exists (
select 1
from public.event_participants mine
join public.event_participants theirs on theirs.group_id = mine.group_id
join public.groups g on g.id = mine.group_id
join public.events e on e.id = g.event_id
where mine.user_id = auth.uid()
and theirs.user_id = other
and mine.status not in ('cancelled', 'declined')
and theirs.status not in ('cancelled', 'declined')
and e.reveal_at <= now()
);
$$;
create or replace function public.can_see_venue(vid uuid)
returns boolean
language sql security definer stable set search_path = public
as $$
select exists (
select 1
from public.event_participants ep
join public.events e on e.id = ep.event_id
left join public.groups g on g.id = ep.group_id
where ep.user_id = auth.uid()
and ep.status not in ('cancelled', 'declined')
and e.reveal_at <= now()
and coalesce(g.venue_id, e.default_venue_id) = vid
);
$$;
create or replace function public.attended_event(eid uuid)
returns boolean
language sql security definer stable set search_path = public
as $$
select exists (
select 1
from public.event_participants ep
join public.events e on e.id = ep.event_id
where ep.event_id = eid
and ep.user_id = auth.uid()
and ep.status not in ('cancelled', 'declined', 'no_show')
and e.event_at <= now()
);
$$;
create or replace function public.join_event(p_event_id uuid)
returns void
language plpgsql security definer set search_path = public
as $$
declare
v_uid uuid := auth.uid();
v_event public.events%rowtype;
v_taken int;
begin
if v_uid is null then
raise exception 'not_authenticated';
end if;
if not exists (
select 1 from public.surveys
where user_id = v_uid and completed_at is not null
) then
raise exception 'survey_incomplete';
end if;
select * into v_event from public.events where id = p_event_id for update;
if not found or v_event.status <> 'open' or v_event.event_at <= now() then
raise exception 'event_not_open';
end if;
if exists (
select 1
from public.event_participants ep
join public.events e on e.id = ep.event_id
where ep.user_id = v_uid
and ep.event_id <> p_event_id
and ep.status not in ('cancelled', 'declined', 'no_show')
and e.status <> 'cancelled'
and e.event_at > v_event.event_at - interval '2 hours'
and e.event_at < v_event.event_at + interval '2 hours'
) then
raise exception 'time_conflict';
end if;
select count(*) into v_taken
from public.event_participants
where event_id = p_event_id
and user_id <> v_uid
and status not in ('cancelled', 'declined', 'no_show');
if v_taken >= v_event.capacity then
raise exception 'event_full';
end if;
insert into public.event_participants as ep (event_id, user_id)
values (p_event_id, v_uid)
on conflict (event_id, user_id) do update
set status = 'joined',
group_id = null,
joined_at = now(),
confirmed_24h_at = null,
confirmed_3h_at = null,
cancelled_at = null
where ep.status in ('cancelled', 'declined');
end;
$$;
create or replace function public.leave_event(p_event_id uuid)
returns void
language plpgsql security definer set search_path = public
as $$
begin
update public.event_participants ep
set status = 'cancelled', cancelled_at = now()
from public.events e
where e.id = ep.event_id
and ep.event_id = p_event_id
and ep.user_id = auth.uid()
and ep.status in ('joined', 'matched', 'confirmed_24h', 'confirmed_3h')
and e.event_at > now();
if not found then
raise exception 'nothing_to_cancel';
end if;
end;
$$;
create or replace function public.create_event(
p_event_at timestamptz,
p_target_group_size int default 4,
p_default_venue_id uuid default null,
p_location_hidden boolean default true,
p_capacity int default 40,
p_title text default null,
p_status public.event_status default 'open'
)
returns uuid
language plpgsql security definer set search_path = public
as $$
declare
v_id uuid;
begin
if not public.is_admin() then
raise exception 'not_admin';
end if;
if p_event_at <= now() then
raise exception 'event_in_the_past';
end if;
insert into public.events
(title, event_at, capacity, target_group_size, reveal_at,
default_venue_id, status, created_by)
values
(p_title, p_event_at, p_capacity, p_target_group_size,
case when p_location_hidden then null else now() end,
p_default_venue_id, p_status, auth.uid())
returning id into v_id;
return v_id;
end;
$$;
create or replace function public.get_open_events()
returns table (
id uuid,
event_at timestamptz,
max_participants int,
spots_left int,
joined boolean
)
language sql security definer stable set search_path = public
as $$
select
e.id,
e.event_at,
e.target_group_size,
greatest(e.capacity - count(ep.id) filter (
where ep.status not in ('cancelled', 'declined', 'no_show')
), 0)::int,
coalesce(bool_or(ep.user_id = auth.uid()
and ep.status not in ('cancelled', 'declined')), false)
from public.events e
left join public.event_participants ep on ep.event_id = e.id
where e.status = 'open' and e.event_at > now()
group by e.id
order by e.event_at;
$$;
create or replace function public.profile_card(p_user_id uuid)
returns jsonb
language sql security definer stable set search_path = public
as $$
select jsonb_build_object(
'id', p.id,
'name', p.display_name,
'emoji', p.avatar_emoji,
'gender', p.gender,
'age', extract(year from age(p.date_of_birth))::int,
'languages', coalesce((select jsonb_agg(l.language order by l.language)
from public.profile_languages l
where l.user_id = p.id), '[]'::jsonb),
'occupation', p.occupation,
'favoriteCoffee', p.favorite_coffee,
'survey', coalesce(s.survey_data, '{}'::jsonb)
)
from public.profiles p
left join public.surveys s on s.user_id = p.id
where p.id = p_user_id;
$$;
create or replace function public.venue_card(p_venue_id uuid)
returns jsonb
language sql security definer stable set search_path = public
as $$
select jsonb_build_object(
'id', v.id,
'name', v.name,
'description', v.description,
'photo', v.photo_url,
'address', v.address,
'website', v.website,
'phone', v.phone,
'mapsUrl', v.maps_url,
'rating', v.rating,
'popularTimes', coalesce(to_jsonb(v.popular_times), '[]'::jsonb)
)
from public.venues v
where v.id = p_venue_id;
$$;
create or replace function public.get_my_events()
returns table (
id uuid,
event_at timestamptz,
reveal_at timestamptz,
status text,
participant_status public.participant_status,
joined boolean,
location_hidden boolean,
max_participants int,
cafe jsonb,
participants jsonb,
my_rating smallint
)
language sql security definer stable set search_path = public
as $$
select
e.id,
e.event_at,
e.reveal_at,
case
when ep.status in ('cancelled', 'declined', 'no_show')
or e.status = 'cancelled' then 'cancelled'
when e.status = 'completed' then 'completed'
when ep.status in ('confirmed_24h', 'confirmed_3h') then 'confirmed'
else 'pending'
end,
ep.status,
ep.status not in ('cancelled', 'declined'),
e.reveal_at > now(),
greatest(e.target_group_size, coalesce(mates.total, 0)),
case when e.reveal_at <= now()
then public.venue_card(coalesce(g.venue_id, e.default_venue_id)) end,
case when e.reveal_at <= now()
then coalesce(mates.cards, '[]'::jsonb) end,
r.rating
from public.event_participants ep
join public.events e on e.id = ep.event_id
left join public.groups g on g.id = ep.group_id
left join public.event_ratings r on r.event_id = e.id and r.user_id = ep.user_id
left join lateral (
select
count(*)::int as total,
jsonb_agg(public.profile_card(m.user_id) order by m.joined_at)
filter (where m.user_id <> ep.user_id) as cards
from public.event_participants m
where m.group_id = ep.group_id
and m.status not in ('cancelled', 'declined')
) mates on ep.group_id is not null
where ep.user_id = auth.uid()
and e.status <> 'draft'
order by e.event_at;
$$;
create or replace function public.get_public_profile(p_user_id uuid)
returns jsonb
language plpgsql security definer stable set search_path = public
as $$
declare
v_stats jsonb;
begin
if not (p_user_id = auth.uid()
or public.is_admin()
or public.shares_revealed_group(p_user_id)) then
return null;
end if;
select jsonb_build_object(
'coffeeTalks', count(distinct e.id),
'cafesVisited', count(distinct coalesce(g.venue_id, e.default_venue_id)),
'peopleMet', count(distinct m.user_id)
) into v_stats
from public.event_participants ep
join public.events e on e.id = ep.event_id and e.status = 'completed'
left join public.groups g on g.id = ep.group_id
left join public.event_participants m
on m.group_id = ep.group_id
and m.user_id <> ep.user_id
and m.status not in ('cancelled', 'declined', 'no_show')
where ep.user_id = p_user_id
and ep.status not in ('cancelled', 'declined', 'no_show');
return public.profile_card(p_user_id) || jsonb_build_object('stats', v_stats);
end;
$$;
create or replace function public.get_my_visited_venues()
returns setof jsonb
language sql security definer stable set search_path = public
as $$
select public.venue_card(visited.venue_id)
from (
select coalesce(g.venue_id, e.default_venue_id) as venue_id,
max(e.event_at) as last_visit
from public.event_participants ep
join public.events e on e.id = ep.event_id and e.status = 'completed'
left join public.groups g on g.id = ep.group_id
where ep.user_id = auth.uid()
and ep.status not in ('cancelled', 'declined', 'no_show')
and coalesce(g.venue_id, e.default_venue_id) is not null
group by 1
) visited
order by visited.last_visit desc;
$$;
