-- Koffito schema on plain Postgres (ported from supabase/migrations, which stay as history).
--
-- Security model: the FastAPI backend is the only database client. It authenticates users
-- itself (see src/koffito/auth) and, inside each request's transaction, sets
-- `app.user_id` to the signed-in user's id. SQL functions read it through app.uid() and
-- enforce who may do what — the same rules that used to sit behind Supabase Auth and RLS.

create extension if not exists pgcrypto;
create extension if not exists citext;
create extension if not exists vector;

-- --- who is calling ------------------------------------------------------------------------
create schema if not exists app;

create or replace function app.uid()
returns uuid
language sql stable
as $$
  select nullif(current_setting('app.user_id', true), '')::uuid;
$$;

create or replace function public.set_updated_at()
returns trigger language plpgsql set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- --- accounts (our own auth) ---------------------------------------------------------------
create table public.users (
  id uuid primary key default gen_random_uuid(),
  email citext not null unique check (char_length(email) <= 254),
  -- Argon2id PHC string; never the password itself.
  password_hash text not null,
  email_verified_at timestamptz,
  failed_logins int not null default 0,
  locked_until timestamptz,
  password_changed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger trg_users_updated_at
before update on public.users
for each row execute function public.set_updated_at();

-- Refresh tokens are stored only as SHA-256 hashes. Each login starts a family; every refresh
-- rotates to a new token in the same family. Presenting an already-rotated token revokes the
-- whole family (someone else is holding a copy).
create table public.refresh_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  family_id uuid not null,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  replaced_by uuid references public.refresh_tokens (id) on delete set null,
  user_agent text,
  created_at timestamptz not null default now()
);
create index idx_refresh_tokens_user on public.refresh_tokens (user_id);
create index idx_refresh_tokens_family on public.refresh_tokens (family_id);

-- Single-use links for email verification and password reset (hash only).
create table public.email_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  purpose text not null check (purpose in ('verify_email', 'reset_password')),
  token_hash text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);
create index idx_email_tokens_user on public.email_tokens (user_id, purpose);

-- --- enums -----------------------------------------------------------------------------------
create type public.gender as enum ('female', 'male', 'non_binary', 'prefer_not_to_say');
create type public.event_status as enum ('draft','open','matched','confirmed','completed','cancelled');
create type public.participant_status as enum ('joined','matched','confirmed_24h','confirmed_3h','declined','cancelled','no_show');
create type public.reservation_status as enum ('pending', 'confirmed', 'cancelled');
create type public.report_status as enum ('open', 'reviewing', 'resolved');
create type public.report_reason as enum ('no-show', 'rude', 'unsafe', 'fake', 'other');

-- --- profiles --------------------------------------------------------------------------------
-- One per user; created by the backend in the same transaction as the account.
create table public.profiles (
  id uuid primary key references public.users (id) on delete cascade,
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
  -- Only changed with `python -m koffito.cli make-admin`; the API never writes it.
  is_admin boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger trg_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

create or replace function public.is_admin()
returns boolean
language sql stable set search_path = public
as $$
  select coalesce((select is_admin from public.profiles where id = app.uid()), false);
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
language plpgsql set search_path = public
as $$
declare
  v_uid uuid := app.uid();
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

-- --- surveys ---------------------------------------------------------------------------------
create or replace function public.is_valid_survey_data(data jsonb)
returns boolean language sql immutable set search_path = public
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
  survey_data jsonb not null default '{}'::jsonb check (public.is_valid_survey_data(survey_data)),
  embedding vector(64),
  embedding_version int,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index idx_surveys_embedding on public.surveys using hnsw (embedding vector_cosine_ops);
create trigger trg_surveys_updated_at
before update on public.surveys
for each row execute function public.set_updated_at();

-- --- venues & events -------------------------------------------------------------------------
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
returns trigger language plpgsql set search_path = public
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
returns trigger language plpgsql set search_path = public
as $$
begin
  if new.venue_id is null then
    select default_venue_id into new.venue_id from public.events where id = new.event_id;
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
  -- The user's own answer to "did this coffee talk happen?"; null until answered.
  attended boolean,
  attendance_note text,
  reveal_opened_at timestamptz,
  -- Set by the reminder job once each reminder went out.
  reminded_24h_at timestamptz,
  reminded_3h_at timestamptz,
  unique (event_id, user_id)
);
create index idx_participants_event on public.event_participants (event_id);
create index idx_participants_user on public.event_participants (user_id);
create index idx_participants_group on public.event_participants (group_id);
create index idx_participants_status on public.event_participants (status);

-- --- reports & ratings -----------------------------------------------------------------------
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

-- Admin-only (the backend only reads it behind require_admin).
create view public.admin_reports as
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

-- --- visibility helpers (who may see what) ---------------------------------------------------
create or replace function public.is_group_member(gid uuid)
returns boolean language sql stable set search_path = public
as $$
  select exists (
    select 1 from public.event_participants
    where group_id = gid and user_id = app.uid() and status not in ('cancelled', 'declined')
  );
$$;

create or replace function public.group_revealed(gid uuid)
returns boolean language sql stable set search_path = public
as $$
  select exists (
    select 1 from public.groups g join public.events e on e.id = g.event_id
    where g.id = gid and e.reveal_at <= now()
  );
$$;

create or replace function public.shares_revealed_group(other uuid)
returns boolean language sql stable set search_path = public
as $$
  select exists (
    select 1
    from public.event_participants mine
    join public.event_participants theirs on theirs.group_id = mine.group_id
    join public.groups g on g.id = mine.group_id
    join public.events e on e.id = g.event_id
    where mine.user_id = app.uid()
      and theirs.user_id = other
      and mine.status not in ('cancelled', 'declined')
      and theirs.status not in ('cancelled', 'declined')
      and e.reveal_at <= now()
  );
$$;

create or replace function public.can_see_venue(vid uuid)
returns boolean language sql stable set search_path = public
as $$
  select exists (
    select 1
    from public.event_participants ep
    join public.events e on e.id = ep.event_id
    left join public.groups g on g.id = ep.group_id
    where ep.user_id = app.uid()
      and ep.status not in ('cancelled', 'declined')
      and e.reveal_at <= now()
      and coalesce(g.venue_id, e.default_venue_id) = vid
  );
$$;

create or replace function public.attended_event(eid uuid)
returns boolean language sql stable set search_path = public
as $$
  select exists (
    select 1
    from public.event_participants ep
    join public.events e on e.id = ep.event_id
    where ep.event_id = eid
      and ep.user_id = app.uid()
      and ep.status not in ('cancelled', 'declined', 'no_show')
      and e.event_at <= now()
  );
$$;

create or replace function public.profile_card(p_user_id uuid)
returns jsonb language sql stable set search_path = public
as $$
  select jsonb_build_object(
    'id', p.id,
    'name', p.display_name,
    'emoji', p.avatar_emoji,
    'gender', p.gender,
    'age', extract(year from age(p.date_of_birth))::int,
    'languages', coalesce((select jsonb_agg(l.language order by l.language)
                           from public.profile_languages l where l.user_id = p.id), '[]'::jsonb),
    'occupation', p.occupation,
    'favoriteCoffee', p.favorite_coffee,
    'survey', coalesce(s.survey_data, '{}'::jsonb)
  )
  from public.profiles p
  left join public.surveys s on s.user_id = p.id
  where p.id = p_user_id;
$$;

create or replace function public.venue_card(p_venue_id uuid)
returns jsonb language sql stable set search_path = public
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

-- --- the signed-in user ----------------------------------------------------------------------
create or replace function public.get_public_profile(p_user_id uuid)
returns jsonb language plpgsql stable set search_path = public
as $$
declare
  v_stats jsonb;
begin
  if not (p_user_id = app.uid() or public.is_admin() or public.shares_revealed_group(p_user_id)) then
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

create or replace function public.get_me()
returns jsonb language sql stable set search_path = public
as $$
  select public.get_public_profile(app.uid())
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
  where p.id = app.uid();
$$;

create or replace function public.get_my_visited_venues()
returns setof jsonb language sql stable set search_path = public
as $$
  select public.venue_card(visited.venue_id)
  from (
    select coalesce(g.venue_id, e.default_venue_id) as venue_id, max(e.event_at) as last_visit
    from public.event_participants ep
    join public.events e on e.id = ep.event_id and e.status = 'completed'
    left join public.groups g on g.id = ep.group_id
    where ep.user_id = app.uid()
      and ep.status not in ('cancelled', 'declined', 'no_show')
      and coalesce(g.venue_id, e.default_venue_id) is not null
    group by 1
  ) visited
  order by visited.last_visit desc;
$$;

-- "Blind" events hide the café until reveal_at; non-blind events get reveal_at = created_at.
create or replace function public.get_my_events()
returns table (
  id uuid,
  event_at timestamptz,
  reveal_at timestamptz,
  status text,
  participant_status public.participant_status,
  joined boolean,
  blind boolean,
  location_hidden boolean,
  reveal_opened boolean,
  max_participants int,
  cafe jsonb,
  participants jsonb,
  attended boolean,
  attendance_note text,
  my_rating smallint,
  my_comment text
)
language sql stable set search_path = public
as $$
  select
    e.id,
    e.event_at,
    e.reveal_at,
    case
      when ep.status in ('cancelled', 'declined', 'no_show') or e.status = 'cancelled' then 'cancelled'
      when e.status = 'completed' then 'completed'
      when ep.status in ('confirmed_24h', 'confirmed_3h') then 'confirmed'
      else 'pending'
    end,
    ep.status,
    ep.status not in ('cancelled', 'declined'),
    e.reveal_at > e.created_at,
    e.reveal_at > now(),
    ep.reveal_opened_at is not null,
    greatest(e.target_group_size, coalesce(mates.total, 0)),
    case when e.reveal_at <= now() then public.venue_card(coalesce(g.venue_id, e.default_venue_id)) end,
    case when e.reveal_at <= now() then coalesce(mates.cards, '[]'::jsonb) end,
    ep.attended,
    ep.attendance_note,
    r.rating,
    r.comment
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
    where m.group_id = ep.group_id and m.status not in ('cancelled', 'declined')
  ) mates on ep.group_id is not null
  where ep.user_id = app.uid() and e.status <> 'draft'
  order by e.event_at;
$$;

-- --- events: join / leave / confirm / reveal / feedback --------------------------------------
create or replace function public.get_open_events()
returns table (id uuid, event_at timestamptz, max_participants int, spots_left int, joined boolean)
language sql stable set search_path = public
as $$
  select
    e.id,
    e.event_at,
    e.target_group_size,
    greatest(e.capacity - count(ep.id) filter (
      where ep.status not in ('cancelled', 'declined', 'no_show')
    ), 0)::int,
    coalesce(bool_or(ep.user_id = app.uid() and ep.status not in ('cancelled', 'declined')), false)
  from public.events e
  left join public.event_participants ep on ep.event_id = e.id
  where e.status = 'open' and e.event_at > now()
  group by e.id
  order by e.event_at;
$$;

create or replace function public.join_event(p_event_id uuid)
returns void language plpgsql set search_path = public
as $$
declare
  v_uid uuid := app.uid();
  v_event public.events%rowtype;
  v_taken int;
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;
  if not exists (select 1 from public.surveys where user_id = v_uid and completed_at is not null) then
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
  where event_id = p_event_id and user_id <> v_uid
    and status not in ('cancelled', 'declined', 'no_show');
  if v_taken >= v_event.capacity then
    raise exception 'event_full';
  end if;
  insert into public.event_participants as ep (event_id, user_id)
  values (p_event_id, v_uid)
  on conflict (event_id, user_id) do update
    set status = 'joined', group_id = null, joined_at = now(),
        confirmed_24h_at = null, confirmed_3h_at = null, cancelled_at = null
    where ep.status in ('cancelled', 'declined');
end;
$$;

create or replace function public.leave_event(p_event_id uuid)
returns void language plpgsql set search_path = public
as $$
begin
  update public.event_participants ep
    set status = 'cancelled', cancelled_at = now()
  from public.events e
  where e.id = ep.event_id
    and ep.event_id = p_event_id
    and ep.user_id = app.uid()
    and ep.status in ('joined', 'matched', 'confirmed_24h', 'confirmed_3h')
    and e.event_at > now();
  if not found then
    raise exception 'nothing_to_cancel';
  end if;
end;
$$;

create or replace function public.confirm_event(p_event_id uuid, p_stage text)
returns void language plpgsql set search_path = public
as $$
declare
  v_uid uuid := app.uid();
  v_event public.events%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;
  if p_stage not in ('24h', '3h') then
    raise exception 'invalid_stage';
  end if;
  select * into v_event from public.events where id = p_event_id;
  if not found or v_event.status in ('cancelled', 'completed', 'draft') or v_event.event_at <= now() then
    raise exception 'event_not_confirmable';
  end if;
  if p_stage = '24h' then
    update public.event_participants
      set status = 'confirmed_24h', confirmed_24h_at = coalesce(confirmed_24h_at, now())
    where event_id = p_event_id and user_id = v_uid and status in ('joined', 'matched');
  else
    update public.event_participants
      set status = 'confirmed_3h',
          confirmed_24h_at = coalesce(confirmed_24h_at, now()),
          confirmed_3h_at = coalesce(confirmed_3h_at, now())
    where event_id = p_event_id and user_id = v_uid
      and status in ('joined', 'matched', 'confirmed_24h');
  end if;
  if not found then
    raise exception 'nothing_to_confirm';
  end if;
end;
$$;

create or replace function public.report_attendance(p_event_id uuid, p_happened boolean, p_note text default null)
returns void language plpgsql set search_path = public
as $$
declare
  v_uid uuid := app.uid();
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;
  update public.event_participants ep
    set attended = p_happened,
        attendance_note = nullif(trim(coalesce(p_note, '')), ''),
        status = case when p_happened then ep.status else 'no_show' end
  from public.events e
  where e.id = ep.event_id
    and ep.event_id = p_event_id
    and ep.user_id = v_uid
    and ep.status not in ('cancelled', 'declined')
    and e.event_at <= now();
  if not found then
    raise exception 'nothing_to_confirm';
  end if;
end;
$$;

create or replace function public.open_reveal(p_event_id uuid)
returns void language plpgsql set search_path = public
as $$
begin
  update public.event_participants ep
    set reveal_opened_at = coalesce(ep.reveal_opened_at, now())
  from public.events e
  where e.id = ep.event_id
    and ep.event_id = p_event_id
    and ep.user_id = app.uid()
    and ep.status not in ('cancelled', 'declined')
    and e.reveal_at <= now();
  if not found then
    raise exception 'not_revealed_yet';
  end if;
end;
$$;

create or replace function public.rate_event(p_event_id uuid, p_rating smallint, p_comment text default '')
returns jsonb language plpgsql set search_path = public
as $$
declare
  v_uid uuid := app.uid();
  v_row public.event_ratings%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;
  if p_rating is null or p_rating < 1 or p_rating > 5 then
    raise exception 'invalid_rating';
  end if;
  if not public.attended_event(p_event_id) then
    raise exception 'not_attended';
  end if;
  insert into public.event_ratings (event_id, user_id, rating, comment)
  values (p_event_id, v_uid, p_rating, coalesce(p_comment, ''))
  on conflict (event_id, user_id) do update
    set rating = excluded.rating, comment = excluded.comment
  returning * into v_row;
  return jsonb_build_object(
    'event_id', v_row.event_id,
    'rating', v_row.rating,
    'comment', v_row.comment,
    'created_at', v_row.created_at,
    'updated_at', v_row.updated_at
  );
end;
$$;

-- --- admin -----------------------------------------------------------------------------------
create or replace function public.create_event(
  p_event_at timestamptz,
  p_target_group_size int default 4,
  p_default_venue_id uuid default null,
  p_location_hidden boolean default true,
  p_capacity int default 40,
  p_title text default null,
  p_status public.event_status default 'open'
)
returns uuid language plpgsql set search_path = public
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
    (title, event_at, capacity, target_group_size, reveal_at, default_venue_id, status, created_by)
  values
    (p_title, p_event_at, p_capacity, p_target_group_size,
     case when p_location_hidden then null else now() end,
     p_default_venue_id, p_status, app.uid())
  returning id into v_id;
  return v_id;
end;
$$;

create or replace function public.admin_list_events()
returns setof public.events language sql stable set search_path = public
as $$
  select * from public.events where public.is_admin();
$$;
