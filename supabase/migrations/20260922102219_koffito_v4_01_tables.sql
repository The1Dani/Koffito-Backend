create extension if not exists "pgcrypto";
create extension if not exists vector;
create type public.gender as enum ('female', 'male', 'non_binary', 'prefer_not_to_say');
create type public.event_status as enum ('draft','open','matched','confirmed','completed','cancelled');
create type public.participant_status as enum ('joined','matched','confirmed_24h','confirmed_3h','declined','cancelled','no_show');
create type public.reservation_status as enum ('pending', 'confirmed', 'cancelled');
create type public.report_status as enum ('open', 'reviewing', 'resolved');
create type public.report_reason as enum ('no-show', 'rude', 'unsafe', 'fake', 'other');
create or replace function public.set_updated_at()
returns trigger language plpgsql
as $$
begin
new.updated_at = now();
return new;
end;
$$;
create table public.profiles (
id uuid primary key references auth.users (id) on delete cascade,
display_name text not null default '',
avatar_emoji text,
avatar_url text,
gender public.gender,
date_of_birth date check (
date_of_birth <= (current_date - interval '18 years')::date
and date_of_birth >= date '1900-01-01'
),
occupation text,
favorite_coffee text,
onboarded_at timestamptz,
is_admin boolean not null default false,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now()
);
create or replace function public.protect_is_admin()
returns trigger language plpgsql
as $$
begin
if current_user in ('authenticated', 'anon') and (
(tg_op = 'INSERT' and new.is_admin)
or (tg_op = 'UPDATE' and new.is_admin is distinct from old.is_admin)
) then
raise exception 'is_admin_is_read_only';
end if;
return new;
end;
$$;
create trigger trg_profiles_protect_is_admin
before insert or update on public.profiles
for each row execute function public.protect_is_admin();
create trigger trg_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();
create or replace function public.is_admin()
returns boolean
language sql security definer stable set search_path = public
as $$
select coalesce((select is_admin from public.profiles where id = auth.uid()), false);
$$;
create table public.user_settings (
user_id uuid primary key references public.profiles (id) on delete cascade,
notifications_enabled boolean not null default true,
reminders_enabled boolean not null default true,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now()
);
create trigger trg_user_settings_updated_at
before update on public.user_settings
for each row execute function public.set_updated_at();
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
insert into public.profiles (id, display_name)
values (
new.id,
coalesce(
nullif(trim(new.raw_user_meta_data ->> 'first_name'), ''),
nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
nullif(split_part(coalesce(new.email, ''), '@', 1), ''),
''
)
);
insert into public.user_settings (user_id) values (new.id);
return new;
end;
$$;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();
create table public.profile_languages (
id uuid primary key default gen_random_uuid(),
user_id uuid not null references public.profiles (id) on delete cascade,
language text not null check (language in ('ro', 'ru', 'en')),
created_at timestamptz not null default now(),
unique (user_id, language)
);
create index idx_profile_languages_lang on public.profile_languages (language);
create or replace function public.set_my_languages(p_languages text[])
returns text[]
language plpgsql security definer set search_path = public
as $$
declare
v_uid uuid := auth.uid();
v_langs text[];
begin
if v_uid is null then
raise exception 'not_authenticated';
end if;
select coalesce(array_agg(distinct lower(trim(l)) order by lower(trim(l))), '{}')
into v_langs
from unnest(coalesce(p_languages, '{}')) as l;
if not v_langs <@ array['ro', 'ru', 'en'] then
raise exception 'unknown_language';
end if;
delete from public.profile_languages
where user_id = v_uid and language <> all (v_langs);
insert into public.profile_languages (user_id, language)
select v_uid, l from unnest(v_langs) as l
on conflict (user_id, language) do nothing;
return v_langs;
end;
$$;
create or replace function public.is_valid_survey_data(data jsonb)
returns boolean language sql immutable
as $$
select jsonb_typeof(data) = 'object'
and not exists (
select 1 from jsonb_each(data) as answer
where jsonb_typeof(answer.value) <> 'array'
);
$$;
create table public.surveys (
id uuid primary key default gen_random_uuid(),
user_id uuid not null unique references public.profiles (id) on delete cascade,
survey_data jsonb not null default '{}'::jsonb
check (public.is_valid_survey_data(survey_data)),
embedding vector(64),
embedding_version int,
completed_at timestamptz,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now()
);
create index idx_surveys_embedding
on public.surveys using hnsw (embedding vector_cosine_ops);
create trigger trg_surveys_updated_at
before update on public.surveys
for each row execute function public.set_updated_at();
create table public.venues (
id uuid primary key default gen_random_uuid(),
name text not null,
description text not null default '',
photo_url text,
address text not null,
website text,
phone text,
maps_url text,
google_place_id text,
latitude double precision,
longitude double precision,
rating numeric(2,1) check (rating between 0 and 5),
popular_times smallint[] check (popular_times is null or cardinality(popular_times) = 7),
capacity int,
is_active boolean not null default true,
created_at timestamptz not null default now()
);
create table public.events (
id uuid primary key default gen_random_uuid(),
title text,
event_at timestamptz not null,
capacity int not null default 40 check (capacity > 0),
target_group_size int not null default 4 check (target_group_size between 2 and 8),
reveal_at timestamptz not null,
default_venue_id uuid references public.venues (id),
status public.event_status not null default 'draft',
created_by uuid references public.profiles (id),
created_at timestamptz not null default now(),
updated_at timestamptz not null default now(),
constraint reveal_before_event check (reveal_at <= event_at)
);
create or replace function public.default_reveal_at()
returns trigger language plpgsql
as $$
begin
if new.reveal_at is null then
new.reveal_at = new.event_at - interval '24 hours';
end if;
return new;
end;
$$;
create trigger trg_events_default_reveal
before insert on public.events
for each row execute function public.default_reveal_at();
create index idx_events_status on public.events (status);
create index idx_events_event_at on public.events (event_at);
create trigger trg_events_updated_at
before update on public.events
for each row execute function public.set_updated_at();
create table public.groups (
id uuid primary key default gen_random_uuid(),
event_id uuid not null references public.events (id) on delete cascade,
venue_id uuid references public.venues (id),
reserved_by uuid references public.profiles (id),
reservation_status public.reservation_status not null default 'pending',
reservation_notes text,
avg_distance real,
created_at timestamptz not null default now()
);
create index idx_groups_event on public.groups (event_id);
create or replace function public.inherit_event_venue()
returns trigger language plpgsql
as $$
begin
if new.venue_id is null then
select default_venue_id into new.venue_id
from public.events where id = new.event_id;
end if;
return new;
end;
$$;
create trigger trg_groups_inherit_venue
before insert on public.groups
for each row execute function public.inherit_event_venue();
create table public.event_participants (
id uuid primary key default gen_random_uuid(),
event_id uuid not null references public.events (id) on delete cascade,
user_id uuid not null references public.profiles (id) on delete cascade,
group_id uuid references public.groups (id) on delete set null,
status public.participant_status not null default 'joined',
joined_at timestamptz not null default now(),
confirmed_24h_at timestamptz,
confirmed_3h_at timestamptz,
cancelled_at timestamptz,
unique (event_id, user_id)
);
create index idx_participants_event on public.event_participants (event_id);
create index idx_participants_user on public.event_participants (user_id);
create index idx_participants_group on public.event_participants (group_id);
create index idx_participants_status on public.event_participants (status);
create table public.reports (
id uuid primary key default gen_random_uuid(),
reporter_id uuid not null references public.profiles (id) on delete cascade,
reported_user_id uuid references public.profiles (id) on delete set null,
event_id uuid references public.events (id) on delete set null,
reason public.report_reason not null,
details text not null check (char_length(trim(details)) >= 10),
status public.report_status not null default 'open',
handled_by uuid references public.profiles (id) on delete set null,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now(),
constraint no_self_report check (reported_user_id is null or reporter_id <> reported_user_id)
);
create index idx_reports_status on public.reports (status);
create trigger trg_reports_updated_at
before update on public.reports
for each row execute function public.set_updated_at();
create view public.admin_reports
with (security_invoker = true) as
select
r.id,
r.reason,
r.details,
r.status,
r.created_at,
r.updated_at,
r.event_id,
r.reporter_id,
reporter.display_name as reported_by,
r.reported_user_id,
reported.display_name as reported_user_name,
r.handled_by
from public.reports r
join public.profiles reporter on reporter.id = r.reporter_id
left join public.profiles reported on reported.id = r.reported_user_id;
create table public.event_ratings (
id uuid primary key default gen_random_uuid(),
event_id uuid not null references public.events (id) on delete cascade,
user_id uuid not null references public.profiles (id) on delete cascade,
rating smallint not null check (rating between 1 and 5),
comment text not null default '',
created_at timestamptz not null default now(),
updated_at timestamptz not null default now(),
unique (event_id, user_id)
);
create index idx_event_ratings_event on public.event_ratings (event_id);
create trigger trg_event_ratings_updated_at
before update on public.event_ratings
for each row execute function public.set_updated_at();
